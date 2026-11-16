r"""Build the proof manifest: every headline claim, the file that proves it, and that file's SHA-256.

The Command Center's "verified build" badge links here. The point is that a reviewer can recompute each
hash and confirm the number on screen came from a named proof run, not from an editor.

Writes:
  docs/PROOF_MANIFEST.md          human-readable table
  command_center/proof_manifest.json   machine-readable, shipped with the app

Run:  .\.venv\Scripts\python.exe scripts\build_proof_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
ART = REPO / "docs" / "artifacts"
OUT_JSON = REPO / "command_center" / "proof_manifest.json"
OUT_MD = REPO / "docs" / "PROOF_MANIFEST.md"

# claim -> (value key path in command_center/data.json, proof file, what the file is)
CLAIMS: list[tuple[str, str, str, str]] = [
    ("Bank variance on assessed merchant-days", "recon.bank_variance",
     "docs/artifacts/html/02_halala_recon_board.html", "Phase 11 reconciliation proof board"),
    ("GL variance on assessed merchant-days", "recon.gl_variance",
     "docs/artifacts/html/02_halala_recon_board.html", "Phase 11 reconciliation proof board"),
    ("Merchant-days not assessed (bank file pending)", "truth.not_assessed_mid_days",
     "docs/artifacts/html/02_halala_recon_board.html", "Phase 11 reconciliation proof board"),
    ("ZATCA chain breaks", "chain.violations",
     "docs/artifacts/html/01_zatca_chain_tape.html", "ZATCA engine re-run, chain tape"),
    ("Worker restarts survived mid-submit", "chain.restarts",
     "docs/artifacts/html/01_zatca_chain_tape.html", "ZATCA engine re-run, chain tape"),
    ("Gold columns traced to source", "lineage.covered",
     "dbt/target/manifest.json", "dbt manifest, column-level lineage"),
    ("Gold columns in total", "lineage.gold_columns",
     "dbt/target/manifest.json", "dbt manifest, column-level lineage"),
    ("dbt models passing on Fabric", "runs.published.fabric.dbt_pass",
     "docs/artifacts/10_fabric_run_evidence.json", "Fabric run evidence"),
    ("Spark skew benchmark rows", "skew.0.rows",
     "docs/artifacts/05_skew_benchmark_20m.json", "20M-row skew benchmark"),
    ("PDPL keys shredded on one erasure", "pdpl.keys",
     "docs/artifacts/html/03_pdpl_shred_restore.html", "PDPL shred and restore proof run"),
    ("PDPL Restore Guard re-shredded a restore", "pdpl.guard_reshredded",
     "docs/artifacts/html/03_pdpl_shred_restore.html", "PDPL shred and restore proof run"),
    ("Signed tax rows kept under legal hold", "pdpl.journal_rows",
     "docs/artifacts/html/03_pdpl_shred_restore.html", "PDPL shred and restore proof run"),
    ("Arabic MDM golden customers", "mdm_gold.goldens",
     "docs/artifacts/html/04_arabic_mdm_board.html", "Arabic MDM proof board"),
]


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_MISSING = object()


def dig(data: dict, dotted: str):
    """Walk a dotted path; a numeric part indexes a list. Returns _MISSING if the path does not resolve."""
    cur = data
    for part in dotted.split("."):
        if part.isdigit() and isinstance(cur, list):
            idx = int(part)
            if idx >= len(cur):
                return _MISSING
            cur = cur[idx]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return len(cur) if isinstance(cur, list) else cur


def main() -> None:
    from mizan.lineage.openlineage import git_sha

    data = json.loads((REPO / "command_center" / "data.json").read_text(encoding="utf-8"))
    rows, missing, unresolved = [], [], []
    for claim, key, rel, what in CLAIMS:
        path = REPO / rel
        digest = sha256(path)
        value = dig(data, key)
        if digest is None:
            missing.append(rel)
        if value is _MISSING:
            unresolved.append(f"{claim} ({key})")
        rows.append({"claim": claim, "value": None if value is _MISSING else value, "data_key": key,
                     "proof_file": rel, "proof_is": what, "sha256": digest})
    # A manifest exists to be trustworthy: refuse to write one with a claim that does not resolve.
    assert not unresolved, "claims that do not resolve in data.json: " + "; ".join(unresolved)
    assert not missing, "proof files not found: " + "; ".join(sorted(set(missing)))

    manifest = {
        "git_sha": git_sha()[:12],
        "generated_from": "command_center/data.json",
        "note": ("Each claim's value is read from the Gold export; the proof file is the artifact that "
                 "produced it. Recompute any sha256 to confirm the file has not changed."),
        "claims": rows,
    }
    OUT_JSON.write_text(json.dumps(manifest, indent=1, sort_keys=False) + "\n",
                        encoding="utf-8", newline="\n")

    md = ["# Proof manifest", "",
          f"Build `{manifest['git_sha']}`. Every headline number in the Command Center, the proof run that",
          "produced it, and that file's SHA-256. Recompute a hash to confirm nothing was edited by hand.", "",
          "| Claim | Value | Proof file | SHA-256 |", "|---|---|---|---|"]
    for r in rows:
        digest = f"`{r['sha256'][:16]}\u2026`" if r["sha256"] else "**file missing**"
        md.append(f"| {r['claim']} | `{r['value']}` | `{r['proof_file']}` | {digest} |")
    md += ["", "Regenerate with `.\\.venv\\Scripts\\python.exe scripts\\build_proof_manifest.py`.", ""]
    OUT_MD.write_text("\n".join(md), encoding="utf-8", newline="\n")

    print(f"{OUT_MD.relative_to(REPO)}  ({len(rows)} claims)")
    print(f"{OUT_JSON.relative_to(REPO)}")


if __name__ == "__main__":
    main()
