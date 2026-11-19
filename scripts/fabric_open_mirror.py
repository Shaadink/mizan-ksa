r"""Open Mirroring: keep an ERP merchant master live in Fabric without writing a pipeline.

    .\.venv\Scripts\python.exe scripts\fabric_open_mirror.py create   # create MR_MIZAN (idempotent)
    .\.venv\Scripts\python.exe scripts\fabric_open_mirror.py seed     # _metadata.json + initial load
    .\.venv\Scripts\python.exe scripts\fabric_open_mirror.py change   # one CDC batch: update, delete, insert
    .\.venv\Scripts\python.exe scripts\fabric_open_mirror.py status   # mirroring status + landing zone listing

Why this exists
---------------
Everywhere else in MIZAN, data arrives because *we* run something: a notebook lands Bronze, dbt builds
Gold. Open mirroring is the opposite contract. A source system drops change files into a OneLake folder
and Fabric maintains the Delta table itself -- no notebook, no pipeline, and no Capacity Units spent on
the copy. It is how a Saudi enterprise gets an SAP or Oracle table into Fabric without a migration
project, which is a question that gets asked in interviews.

What is mirrored
----------------
`erp.merchant_master`: the merchant and store reference data, which genuinely originates outside the
pipeline (it is an owner-approved seed, not something MIZAN computes). That makes it the one table in
the project with a real claim to arriving this way.

What is NOT done, and why
-------------------------
Gold still reads `dbt/seeds/merchant_store_reference.csv`, not this mirror. Pointing Gold at a mirrored
database would make the pipeline depend on a Fabric-only feature, so it would stop building on DuckDB
locally and in CI -- and "the same models run locally and on Fabric" is worth more than the tidiness of
a single source. The mirror is a working parallel implementation, not a load-bearing one. Said plainly
in HONESTY.md rather than left for a reviewer to discover.

Format (docs: fabric/mirroring/open-mirroring-landing-zone-format)
-----------------------------------------------------------------
Files/LandingZone/<table>/_metadata.json         {"keyColumns": [...]}, immutable once written
Files/LandingZone/<table>/00000000000000000001.parquet   20-digit, continuous, monotonically increasing
  - initial load omits __rowMarker__ entirely: Fabric treats the whole file as INSERT
  - incremental files carry __rowMarker__ as the FINAL column: 0 insert, 1 update, 2 delete, 4 upsert
  - an updated row must carry every column, not just the changed ones
  - row order within a file is the order the changes are applied
"""

from __future__ import annotations

import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mizan.orchestration.fabric_client import sp_token  # noqa: E402
from mizan.privacy.crypto import load_dotenv  # noqa: E402

API = "https://api.fabric.microsoft.com/v1"
DFS = "https://onelake.dfs.fabric.microsoft.com"
MIRROR_NAME = "MR_MIZAN"
TABLE = "merchant_master"
KEY_COLUMNS = ["merchant_id"]
SEED = REPO / "dbt" / "seeds" / "merchant_store_reference.csv"
ROW_MARKER = "__rowMarker__"
INSERT, UPDATE, DELETE = 0, 1, 2


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"{name} missing from .env (run scripts/fabric_provision.py first)")
    return v


def _req(method: str, url: str, token: str, data: bytes | None = None, headers: dict | None = None):
    if not url.startswith("https://"):
        raise ValueError(url)
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)  # noqa: S310 (https checked)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _api(method: str, path: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    st, h, raw = _req(method, f"{API}{path}", token, data, {"Content-Type": "application/json"})
    return st, h, raw.decode("utf-8", "replace")


# ----------------------------------------------------------------------------- landing zone format

def metadata_file() -> bytes:
    """`keyColumns` is what makes update and delete possible; without it every file is append-only.

    It cannot be changed after the first write, so it is declared once here rather than inferred.
    """
    return json.dumps({"keyColumns": KEY_COLUMNS}, indent=1).encode("utf-8") + b"\n"


def landing_file_name(sequence: int) -> str:
    """20 digits, continuous and monotonically increasing: Fabric applies files in this order."""
    if sequence < 1:
        raise ValueError("landing zone files are numbered from 1")
    return f"{sequence:020d}.parquet"


def read_seed() -> list[dict]:
    with SEED.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cdc_batch(rows: list[dict]) -> list[dict]:
    """One believable day at the ERP: a till added, a store closed, a store opened.

    Deliberately touches MID100044 -- the merchant behind "follow one riyal" -- so the change can be
    pointed at something the rest of the project already talks about.

    The DELETE row carries the **whole** row, although the format only requires the key columns. That
    is not redundancy, it is a constraint found by hitting it: DuckDB marks a Parquet column REQUIRED
    when the data it is given contains no nulls, so the initial load produced a non-nullable schema.
    A delete row padded with nulls then arrives as nullable, and Fabric rejects the batch with
    `SchemaMergeFailure ... Incoming type: 'string' (Nullable: True), existing type: ... (Nullable:
    False)` and stops replicating that table. Sending the full row keeps every file's schema identical.
    A source whose initial load already contains nulls would not have this problem.
    """
    by_id = {r["merchant_id"]: r for r in rows}
    updated = dict(by_id["MID100044"], register_count="6")
    closed = dict(by_id["MID100120"])
    opened = {"merchant_id": "MID100121", "store_id": "ST121", "channel": "POS",
              "egs_id": "EGS-04", "city": "Abha", "register_count": "3"}
    return [dict(updated, **{ROW_MARKER: UPDATE}),
            dict(closed, **{ROW_MARKER: DELETE}),
            dict(opened, **{ROW_MARKER: INSERT})]


def write_parquet(rows: list[dict], columns: list[str], out: Path) -> None:
    """DuckDB writes the Parquet, so open mirroring adds no dependency to the project.

    `__rowMarker__` must be the final column, and it is an integer, so the column order here is the
    file's column order -- not whatever a dict happens to iterate in.
    """
    import duckdb
    if ROW_MARKER in columns and columns[-1] != ROW_MARKER:
        raise ValueError(f"{ROW_MARKER} must be the final column")
    ints = (ROW_MARKER, "register_count")
    ddl = ", ".join(f'"{c}" {"INTEGER" if c in ints else "VARCHAR"}' for c in columns)
    con = duckdb.connect()
    try:
        con.execute(f"CREATE TABLE t ({ddl})")
        placeholders = ", ".join("?" * len(columns))       # count only; every value is bound
        con.executemany(f"INSERT INTO t VALUES ({placeholders})",  # noqa: S608 (no interpolated data)
                        [[(r.get(c) or None) if r.get(c) != 0 else 0 for c in columns] for r in rows])
        con.execute("COPY t TO ? (FORMAT PARQUET)", [out.as_posix()])
    finally:
        con.close()


# ----------------------------------------------------------------------------- Fabric calls

def find_mirror(token: str) -> dict | None:
    st, _, body = _api("GET", f"/workspaces/{env('FABRIC_WORKSPACE_ID')}/mirroredDatabases", token)
    if st != 200:
        raise RuntimeError(f"list mirrored databases: {st} {body[:300]}")
    return next((m for m in json.loads(body)["value"] if m["displayName"] == MIRROR_NAME), None)


def create(token: str) -> dict:
    existing = find_mirror(token)
    if existing:
        print(f"{MIRROR_NAME} already exists: {existing['id']}")
        return existing
    import base64
    mirroring = {"properties": {
        "source": {"type": "GenericMirror", "typeProperties": {}},
        "target": {"type": "MountedRelationalDatabase",
                   "typeProperties": {"format": "Delta", "defaultSchema": "erp"}}}}
    body = {"displayName": MIRROR_NAME,
            "description": "Open mirroring landing zone: ERP merchant master pushed as CDC, no pipeline.",
            "definition": {"parts": [{"path": "mirroring.json",
                                      "payload": base64.b64encode(json.dumps(mirroring).encode()).decode(),
                                      "payloadType": "InlineBase64"}]}}
    st, _, raw = _api("POST", f"/workspaces/{env('FABRIC_WORKSPACE_ID')}/mirroredDatabases", token, body)
    if st not in (200, 201, 202):
        raise RuntimeError(f"create {MIRROR_NAME}: {st} {raw[:400]}")
    item = json.loads(raw)
    print(f"created {MIRROR_NAME}: {item['id']}")
    return item


def start(token: str, mirror_id: str) -> None:
    ws = env("FABRIC_WORKSPACE_ID")
    st, _, raw = _api("POST", f"/workspaces/{ws}/mirroredDatabases/{mirror_id}/startMirroring", token, {})
    print(f"startMirroring: {st} {raw[:200] or '(empty)'}")


def onelake_put(token: str, mirror_id: str, rel: str, content: bytes) -> None:
    ws = env("FABRIC_WORKSPACE_ID")
    url = f"{DFS}/{ws}/{mirror_id}/Files/{urllib.parse.quote(rel)}"
    st, _, body = _req("PUT", url + "?resource=file&overwrite=true", token, b"", {"Content-Length": "0"})
    if st not in (200, 201):
        raise RuntimeError(f"create {rel}: {st} {body[:300]!r}")
    st, _, body = _req("PATCH", f"{url}?action=append&position=0", token, content,
                       {"Content-Length": str(len(content)), "Content-Type": "application/octet-stream"})
    if st not in (200, 202):
        raise RuntimeError(f"append {rel}: {st} {body[:300]!r}")
    st, _, body = _req("PATCH", f"{url}?action=flush&position={len(content)}", token, b"",
                       {"Content-Length": "0"})
    if st not in (200, 201):
        raise RuntimeError(f"flush {rel}: {st} {body[:300]!r}")
    print(f"  wrote {rel}  ({len(content):,} bytes)")


def list_landing(token: str, mirror_id: str) -> list[str]:
    ws = env("FABRIC_WORKSPACE_ID")
    q = urllib.parse.urlencode({"resource": "filesystem", "recursive": "true",
                                "directory": f"{mirror_id}/Files/LandingZone"})
    st, _, raw = _req("GET", f"{DFS}/{ws}?{q}", token)
    if st != 200:
        return []
    return [p["name"].split("Files/LandingZone/", 1)[-1] for p in json.loads(raw).get("paths", [])]


# ----------------------------------------------------------------------------- commands

def _tokens() -> tuple[str, str]:
    t, c, s = env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET")
    return sp_token(t, c, s), sp_token(t, c, s, scope="https://storage.azure.com/.default")


def cmd_seed(api_tok: str, sto_tok: str, mirror_id: str) -> None:
    rows = read_seed()
    columns = list(rows[0])                                   # initial load carries NO __rowMarker__
    out = REPO / "tmp" / "openmirror" / landing_file_name(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_parquet(rows, columns, out)
    onelake_put(sto_tok, mirror_id, f"LandingZone/{TABLE}/_metadata.json", metadata_file())
    onelake_put(sto_tok, mirror_id, f"LandingZone/{TABLE}/{landing_file_name(1)}", out.read_bytes())
    print(f"initial load: {len(rows)} rows, key {KEY_COLUMNS}, no {ROW_MARKER} (whole file is INSERT)")


def cmd_change(api_tok: str, sto_tok: str, mirror_id: str) -> None:
    rows = read_seed()
    batch = cdc_batch(rows)
    columns = [*rows[0], ROW_MARKER]
    existing = [f for f in list_landing(sto_tok, mirror_id) if f.endswith(".parquet")]
    nxt = max((int(Path(f).stem) for f in existing), default=0) + 1
    out = REPO / "tmp" / "openmirror" / landing_file_name(nxt)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_parquet(batch, columns, out)
    onelake_put(sto_tok, mirror_id, f"LandingZone/{TABLE}/{landing_file_name(nxt)}", out.read_bytes())
    for r in batch:
        print(f"  {['INSERT', 'UPDATE', 'DELETE'][r[ROW_MARKER]]:6s} {r['merchant_id']}")


def cmd_reset(api_tok: str, sto_tok: str, mirror_id: str) -> None:
    """Drop the table folder, which is the documented way to restart replication for one table.

    Needed after a schema merge failure: the table stops replicating and no later file is read until
    the folder is recreated. Dropping the folder drops the mirrored table with it.
    """
    ws = env("FABRIC_WORKSPACE_ID")
    url = f"{DFS}/{ws}/{mirror_id}/Files/LandingZone/{TABLE}?recursive=true"
    st, _, body = _req("DELETE", url, sto_tok)
    print(f"drop LandingZone/{TABLE}: {st} {body[:200]!r}")


def cmd_verify(api_tok: str, sto_tok: str, mirror_id: str) -> None:
    """Read the mirrored table back over its SQL endpoint and check the three changes landed.

    The point of a mirror is the table, not the files, so the proof has to come from the table. Fabric
    applied the DELETE with a Delta deletion vector, which a naive Parquet read would miss entirely --
    reading the rows through the endpoint is both simpler and the way a consumer would really see it.
    """
    import struct

    import pyodbc
    ws = env("FABRIC_WORKSPACE_ID")
    st, _, raw = _api("GET", f"/workspaces/{ws}/mirroredDatabases/{mirror_id}", api_tok)
    if st != 200:
        raise RuntimeError(f"get mirrored database: {st} {raw[:300]}")
    ep = json.loads(raw)["properties"]["sqlEndpointProperties"]
    tok = sp_token(env("FABRIC_TENANT_ID"), env("FABRIC_CLIENT_ID"), env("FABRIC_CLIENT_SECRET"),
                   scope="https://database.windows.net/.default").encode("utf-16-le")
    cn = pyodbc.connect(
        f"Driver={{ODBC Driver 18 for SQL Server}};Server={ep['connectionString']},1433;"
        f"Database={ep['id']};Encrypt=yes;TrustServerCertificate=no",
        attrs_before={1256: struct.pack("<i", len(tok)) + tok})          # SQL_COPT_SS_ACCESS_TOKEN
    try:
        q = cn.cursor()
        # The only interpolation is TABLE, a module constant; every value is bound as a parameter.
        total = q.execute(f"SELECT COUNT(*) FROM erp.{TABLE}").fetchone()[0]                 # noqa: S608
        one = f"SELECT register_count, city FROM erp.{TABLE} WHERE merchant_id = ?"          # noqa: S608
        cnt = f"SELECT COUNT(*) FROM erp.{TABLE} WHERE merchant_id = ?"                      # noqa: S608
        upd = q.execute(one, "MID100044").fetchone()
        gone = q.execute(cnt, "MID100120").fetchone()[0]
        new = q.execute(one, "MID100121").fetchone()
    finally:
        cn.close()
    checks = [("rows", total, 121),
              ("MID100044 register_count (UPDATE)", upd[0] if upd else None, 6),
              ("MID100120 rows left (DELETE)", gone, 0),
              ("MID100121 city (INSERT)", new[1] if new else None, "Abha")]
    for name, got, want in checks:
        print(f"  {'PASS' if got == want else 'FAIL'}  {name}: {got!r} (expected {want!r})")
    if any(got != want for _, got, want in checks):
        raise SystemExit("mirrored table does not match the changes that were pushed")


def cmd_status(api_tok: str, sto_tok: str, mirror_id: str) -> None:
    ws = env("FABRIC_WORKSPACE_ID")
    st, _, raw = _api("POST", f"/workspaces/{ws}/mirroredDatabases/{mirror_id}/getMirroringStatus",
                      api_tok, {})
    print(f"mirroring status: {st} {raw[:300]}")
    st, _, raw = _api("POST", f"/workspaces/{ws}/mirroredDatabases/{mirror_id}/getTablesMirroringStatus",
                      api_tok, {})
    print(f"table status: {st} {raw[:600]}")
    files = list_landing(sto_tok, mirror_id)
    print(f"landing zone ({len(files)} entries):")
    for f in sorted(files):
        print("   ", f)


def main() -> None:
    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    api_tok, sto_tok = _tokens()
    if cmd == "create":
        item = create(api_tok)
        start(api_tok, item["id"])
        return
    mirror = find_mirror(api_tok)
    if not mirror:
        raise SystemExit(f"{MIRROR_NAME} does not exist yet -- run `create` first")
    fn = {"seed": cmd_seed, "change": cmd_change, "status": cmd_status,
          "reset": cmd_reset, "verify": cmd_verify, "start": None}.get(cmd)
    if cmd == "start":
        start(api_tok, mirror["id"])
    elif fn:
        fn(api_tok, sto_tok, mirror["id"])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
