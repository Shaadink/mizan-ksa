"""Answer a PDPL right-of-access or portability request for one person.

    .\\.venv\\Scripts\\python.exe scripts\\subject_access.py --national-id 1012345678
    .\\.venv\\Scripts\\python.exe scripts\\subject_access.py --source-ref CUST-000123 --portability
    .\\.venv\\Scripts\\python.exe scripts\\subject_access.py --national-id 1012345678 --out dsar.json

**This produces personal data in the clear.** By default it prints a summary only -- what is held, how
many records, what is withheld and why -- and nothing sensitive reaches the terminal or a shell history.
`--out` writes the full report to a file, which is the deliberate act: it creates a new cleartext copy of
someone's personal data outside every control that protects it at rest.

`docs/RUNBOOKS.md` says to deliver that file through a channel the subject can be authenticated on, and
destroy it afterwards. This script will not delete it for you, and it will not email it.

An erased subject returns ERASED with the tombstone, never a partial record assembled from whatever
erasure left behind.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def summarise(report: dict) -> str:
    """What is held, with no personal data in it. Safe for a terminal, a ticket, or a screenshot."""
    lines = [f"status: {report['status']}", f"generated: {report['generated_at']}"]
    if report["status"] == "NOT_FOUND":
        return "\n".join([*lines, "", *report["notes"]])
    lines.append(f"subject tokens: {len(report['subject_tokens'])}")
    if report["status"] == "ERASED":
        for t in report.get("erasure", []):
            lines.append(f"  erased {t['subject_token_id']} by {t['dsr_id']} "
                         f"({t['legal_hold_class']}) at {t['tombstoned_at']}")
    for name, count in sorted(report.get("record_counts", {}).items()):
        lines.append(f"  {name}: {count} record(s)")
    if report.get("withheld"):
        lines.append("withheld:")
        lines += [f"  {name}: {reason}" for name, reason in sorted(report["withheld"].items())]
    if report.get("notes"):
        lines += ["notes:", *(f"  {n}" for n in report["notes"])]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--national-id", help="national ID or Iqama, as the subject gave it")
    who.add_argument("--source-ref", help="the customer reference in a source system")
    parser.add_argument("--portability", action="store_true",
                        help="the portability subset: data the subject provided, machine-readable")
    parser.add_argument("--out", type=Path,
                        help="write the FULL report here. This creates a cleartext copy of personal data.")
    parser.add_argument("--requested-by", default="dpo@najd.example")
    args = parser.parse_args(argv)

    from mizan.privacy.access import portability_payload, subject_access
    from mizan.privacy.crypto import Keys, load_dotenv
    from mizan.spark.lake import Lake
    from mizan.spark.session import TableLocator, get_spark

    load_dotenv()
    lake = Lake(get_spark("local", app="mizan-subject-access"),
                TableLocator("local", str(REPO / "data" / "lake")))
    report = subject_access(lake, Keys.from_env(), source_ref=args.source_ref,
                            national_id=args.national_id, requested_by=args.requested_by)

    print(summarise(report))
    if args.out:
        payload = portability_payload(report) if args.portability else report
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
                            encoding="utf-8")
        print(f"\nWROTE CLEARTEXT PERSONAL DATA to {args.out}")
        print("Deliver it to an authenticated subject, then destroy it. "
              "See docs/RUNBOOKS.md#answering-a-right-of-access-request.")
    elif report["status"] == "DISCLOSED":
        print("\n(summary only; re-run with --out FILE to produce the full report)")
    return 0 if report["status"] in ("DISCLOSED", "ERASED", "NOT_FOUND") else 1


if __name__ == "__main__":
    raise SystemExit(main())
