"""OpenLineage for MIZAN (I-13): Gold column lineage from the dbt manifest, run manifests with run_id + git_sha +
Delta snapshot versions, and plain-JSON events POSTed to Marquez (no client library needed).

    python -m mizan.lineage.openlineage --manifest dbt/target/manifest.json --duckdb tmp/mizan_gold.duckdb \
        --lake data/lake --out data/out/lineage/gold_column_lineage.json
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from mizan.common.delta_snapshot import delta_rel

REPO = Path(__file__).resolve().parents[3]
NAMESPACE_LH, NAMESPACE_WH = "fabric://mizan-ksa-dev/LH_MIZAN", "fabric://mizan-ksa-dev/WH_MIZAN"
PRODUCER = "https://github.com/Shaadink/mizan-ksa"
SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
COL_FACET = "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
SCHEMA_FACET = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"


def git_sha() -> str:
    """HEAD commit, read from .git directly (works in containers that have no git binary)."""
    git = REPO / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        loose = git / ref
        if loose.exists():
            return loose.read_text(encoding="utf-8").strip()
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        pass
    return "unknown"


_SOURCE_SCHEMA = {"slv_lakehouse": "slv", "quarantine_lakehouse": "quarantine", "meta_lakehouse": "meta"}


def _relation(unique_id: str) -> str:
    """dbt unique_id -> 'slv.payment_lifecycle' / 'gld.<model or seed>'."""
    parts = unique_id.split(".")
    if parts[0] == "source":
        return f"{_SOURCE_SCHEMA[parts[-2]]}.{parts[-1]}"
    return f"gld.{parts[-1]}"


def dataset(rel: str) -> tuple[str, str]:
    schema, table = rel.split(".", 1)
    return (NAMESPACE_WH if schema == "gld" else NAMESPACE_LH), f"{schema}.{table}"


def column_lineage(manifest: dict, columns: dict[str, list[str]], overrides: dict) -> dict[str, dict[str, list[str]]]:
    """-> {model: {output column: ['rel.column', ...]}}. Raises when any Gold column has no input (I-13: 100%)."""
    out: dict[str, dict[str, list[str]]] = {}
    missing = []
    for node in manifest["nodes"].values():
        if node["resource_type"] != "model":
            continue
        model = node["name"]
        ups = [_relation(u) for u in node["depends_on"]["nodes"]]
        ov = overrides.get(model, {})
        out[model] = {}
        for col in columns.get(f"gld.{model}", []):
            inputs = list(ov.get(col, [])) or [f"{u}.{col}" for u in ups if col in columns.get(u, [])]
            for i in inputs:
                rel, c = i.rsplit(".", 1)
                if c not in columns.get(rel, []):
                    raise ValueError(f"{model}.{col}: lineage input {i} does not exist")
            if not inputs:
                missing.append(f"{model}.{col}")
            out[model][col] = sorted(set(inputs))
    if missing:
        raise ValueError(f"Gold columns without lineage: {missing}")
    return out


def collect_columns(duck_path: Path, lake_root: Path) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    """-> ({relation: [column, ...]}, {relation: {column: data_type}}) for Gold (DuckDB) and the Lakehouse (catalog)."""
    import duckdb
    cols: dict[str, list[str]] = {}
    types: dict[str, dict[str, str]] = {}

    def add(rel: str, col: str, typ: str) -> None:
        cols.setdefault(rel, []).append(col)
        types.setdefault(rel, {})[col] = typ

    con = duckdb.connect(Path(duck_path).as_posix(), read_only=True)
    try:
        for t, c, typ in con.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                                     "WHERE table_schema = 'gld' ORDER BY table_name, ordinal_position").fetchall():
            add(f"gld.{t}", c, typ)
        # cc is a read_parquet(...) list built from our own lake paths, with quotes escaped; no user input.
        cc = delta_rel(Path(lake_root) / "LH_MIZAN" / "meta" / "column_classification")
        for s_, t, c, typ in con.execute(
                f"SELECT schema_name, table_name, column_name, data_type FROM {cc}").fetchall():  # noqa: S608
            add(f"{s_}.{t}", c, typ)
        for c, typ, *_ in con.execute(f"DESCRIBE SELECT * FROM {cc}").fetchall():  # noqa: S608
            add("meta.column_classification", c, typ)
    finally:
        con.close()
    return cols, types


def build(manifest_path: Path, duck_path: Path, lake_root: Path, out: Path | None = None) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    overrides = {k: v for k, v in json.loads((REPO / "dbt" / "lineage_overrides.json").read_text(
        encoding="utf-8")).items() if not k.startswith("_")}
    cols, types = collect_columns(duck_path, lake_root)
    lin = column_lineage(manifest, cols, overrides)
    used = {i.rsplit(".", 1)[0] for m in lin.values() for ins in m.values() for i in ins} | {f"gld.{m}" for m in lin}
    doc = {"generated_at": datetime.now(UTC).isoformat(), "git_sha": git_sha(), "column_lineage": lin,
           "columns": {k: v for k, v in cols.items() if k.startswith("gld.")},
           "types": {k: types[k] for k in sorted(used)}}
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    return doc


# ----------------------------------------------------------------------------- events + transport

def run_event(event_type: str, job: str, run_id: str, *, inputs: list[str] = (), outputs: list[str] = (),
              lineage: dict | None = None, columns: dict | None = None, types: dict | None = None,
              sha: str = "",
              snapshots: dict | None = None, parent: tuple[str, str] | None = None) -> dict:
    if event_type not in ("START", "COMPLETE", "FAIL", "ABORT"):
        raise ValueError(event_type)
    run_facets = {"mizan_run": {"_producer": PRODUCER, "_schemaURL": f"{PRODUCER}/facets/MizanRunFacet.json",
                                "git_sha": sha, "snapshot_versions": snapshots or {}}}
    if parent:
        run_facets["parent"] = {"_producer": PRODUCER,
                                "_schemaURL": "https://openlineage.io/spec/facets/1-0-1/ParentRunFacet.json",
                                "run": {"runId": parent[1]}, "job": {"namespace": "mizan-ksa", "name": parent[0]}}

    def ds(rel: str, with_lineage: bool) -> dict:
        ns, name = dataset(rel)
        facets = {}
        if types and rel in types:
            facets["schema"] = {"_producer": PRODUCER, "_schemaURL": SCHEMA_FACET,
                                "fields": [{"name": c, "type": t} for c, t in types[rel].items()]}
        elif columns and rel in columns:
            facets["schema"] = {"_producer": PRODUCER, "_schemaURL": SCHEMA_FACET,
                                "fields": [{"name": c, "type": "UNKNOWN"} for c in columns[rel]]}
        if with_lineage and lineage and rel.startswith("gld.") and rel[4:] in lineage:
            fields = {}
            for col, ins in lineage[rel[4:]].items():
                fields[col] = {"inputFields": [{"namespace": dataset(i.rsplit(".", 1)[0])[0],
                                                "name": i.rsplit(".", 1)[0], "field": i.rsplit(".", 1)[1]}
                                               for i in ins]}
            facets["columnLineage"] = {"_producer": PRODUCER, "_schemaURL": COL_FACET, "fields": fields}
        return {"namespace": ns, "name": name, "facets": facets}

    return {"eventType": event_type, "eventTime": datetime.now(UTC).isoformat(), "producer": PRODUCER,
            "schemaURL": SCHEMA_URL, "run": {"runId": run_id, "facets": run_facets},
            "job": {"namespace": "mizan-ksa", "name": job, "facets": {}},
            "inputs": [ds(r, False) for r in inputs], "outputs": [ds(r, True) for r in outputs]}


def post(events: list[dict], url: str) -> int:
    """POST each event to Marquez (or any OpenLineage HTTP endpoint). Returns the number accepted."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(url)
    ok = 0
    for e in events:
        req = urllib.request.Request(url, data=  # noqa: S310 (scheme checked above)
                                     json.dumps(e).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (scheme checked above)
            ok += 1 if r.status in (200, 201, 204) else 0
    return ok


def gold_events(doc: dict, run_id: str | None = None, snapshots: dict | None = None,
                parent: tuple[str, str] | None = None) -> list[dict]:
    """One START/COMPLETE pair per Gold model, carrying schema + column lineage facets."""
    run_id = run_id or str(uuid.uuid4())
    events = []
    cols = doc["columns"]
    for model, lin in sorted(doc["column_lineage"].items()):
        inputs = sorted({i.rsplit(".", 1)[0] for ins in lin.values() for i in ins})
        mid = str(uuid.uuid5(uuid.UUID(run_id), model))
        for et in ("START", "COMPLETE"):
            events.append(run_event(et, f"dbt.gld.{model}", mid, inputs=inputs, outputs=[f"gld.{model}"],
                                    lineage=doc["column_lineage"], columns=cols, types=doc.get("types"),
                                    sha=doc["git_sha"],
                                    snapshots=snapshots, parent=parent))
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=REPO / "dbt" / "target" / "manifest.json")
    ap.add_argument("--duckdb", type=Path, required=True)
    ap.add_argument("--lake", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=REPO / "data" / "out" / "lineage" / "gold_column_lineage.json")
    ap.add_argument("--marquez", default=None, help="e.g. http://localhost:5000/api/v1/lineage")
    a = ap.parse_args()
    doc = build(a.manifest, a.duckdb, a.lake, a.out)
    n = sum(len(v) for v in doc["column_lineage"].values())
    print(f"{len(doc['column_lineage'])} Gold models, {n} columns, 100% with lineage -> {a.out}")
    if a.marquez:
        print(f"posted {post(gold_events(doc), a.marquez)} events to {a.marquez}")


if __name__ == "__main__":
    main()
