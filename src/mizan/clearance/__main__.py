"""Run every invoice request through the ZATCA chain with the planted fault plan.

.\\.venv\\Scripts\\python.exe -m mizan.clearance --data data/generated --out data/out/zatca

Writes ctl.invoice_outbox / audit.zatca_chain_journal / ctl.egs_chain_state as JSONL (Phase 3 lands them in
Delta), the chain-verifier result, and chain_tape.md (Artifact 1 source table).
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from collections import Counter
from pathlib import Path

from mizan.clearance.chain_verifier import verify_chain
from mizan.clearance.engine import process_requests
from mizan.clearance.mock_fatoora import MockFatoora


def tape_markdown(run, egs: str, lo: int, hi: int) -> str:
    rows = sorted((r for r in run.store.invoice_outbox.values() if r.egs_id == egs and lo <= r.icv <= hi),
                  key=lambda r: r.icv)
    out = ["| ICV | request | PIH (prev hash) | invoice_hash | attempts | path | final state |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        path = " -> ".join(
            ("RESTART: SUBMITTING->UNKNOWN_OUTCOME" if h["event"] == "RECOVERED_AFTER_RESTART"
             else f"{h['http_status'] or 'TIMEOUT'}:{h['state']}")
            for h in r.history if h["event"] in ("RESPONSE", "RECOVERED_AFTER_RESTART"))
        note = f" (corrects ICV {next(x.icv for x in rows if x.invoice_uuid == r.corrects_invoice_uuid)})" \
            if r.corrects_invoice_uuid else ""
        out.append(f"| {r.icv} | {r.request_id}{note} | `{r.pih[:12]}...` | `{r.invoice_hash[:12]}...` | "
                   f"{r.attempts} | {path} | **{r.state}** |")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/generated")
    ap.add_argument("--out", default="data/out/zatca")
    args = ap.parse_args()
    data, out = Path(args.data), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (data / "zatca/invoice_requests.jsonl").open(encoding="utf-8") as f:
        reqs = [json.loads(line) for line in f]
    plan = json.loads((data / "zatca/fatoora_fault_plan.json").read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    run = process_requests(reqs, MockFatoora(plan))
    secs = time.perf_counter() - t0

    with (out / "invoice_outbox.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in sorted(run.store.invoice_outbox.values(), key=lambda r: (r.egs_id, r.icv)):
            d = {k: v for k, v in r.__dict__.items() if k != "signed_xml"}
            f.write(json.dumps(d, sort_keys=True, ensure_ascii=False) + "\n")
    with (out / "zatca_chain_journal.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for k in sorted(run.store.zatca_chain_journal):
            j = dict(run.store.zatca_chain_journal[k])
            j["signed_xml_b64"] = base64.b64encode(j.pop("signed_xml")).decode("ascii")
            f.write(json.dumps(j, sort_keys=True) + "\n")
    (out / "egs_chain_state.json").write_text(
        json.dumps(run.store.egs_chain_state, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    violations = verify_chain(run.store.zatca_chain_journal.values())
    tamper = plan["tamper"][0]
    tampered = {k: v for k, v in run.store.zatca_chain_journal.items() if k != (tamper["egs_id"], tamper["icv"])}
    summary = {
        "documents": len(run.store.invoice_outbox), "requests": len(reqs), "seconds": round(secs, 1),
        "states": dict(sorted(Counter(r.state for r in run.store.invoice_outbox.values()).items())),
        "worker_restarts": run.restarts, "corrections": len(run.corrections),
        "chain_violations": violations,
        "tamper_demo_violations": verify_chain(tampered.values()),
        "max_gl_calls_per_sale": max(run.gl.calls.values()), "gl_postings": len(run.gl.postings),
    }
    (out / "chain_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    tape = plan["tape"]
    (out / "chain_tape.md").write_text(tape_markdown(run, tape["egs_id"], 100, 105), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "tamper_demo_violations"}, indent=2))
    print(f"tamper demo: {len(summary['tamper_demo_violations'])} violations detected")


if __name__ == "__main__":
    main()
