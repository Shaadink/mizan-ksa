"""The canonical headline numbers, derived from the repository rather than remembered.

This project's own rule is that every figure is generated, never typed. The rule had been applied to the
Command Center and not to the documents a reader actually opens first, so `README.md` carried "76 / 76" Gold
columns while `docs/ONE_PAGER.md` said 91/91 thirty-four lines below its own table that also said 76. External
reviewers found it before we did, which is the correct outcome and an embarrassing one.

This module is the single source of truth. It reads the exported Gold snapshot and the repository itself, and
`tests/test_doc_facts_sync.py` fails the build when a document disagrees with it.

Run it to see what the documents must say:
    .\\.venv\\Scripts\\python.exe scripts\\facts.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "command_center" / "data.json"

# The modelled window. 2026-02-12 to 2026-03-03 inclusive, Asia/Riyadh.
WINDOW_DAYS = 20


def _snapshot() -> dict:
    if not DATA.exists():
        raise SystemExit(f"{DATA} not built: run scripts/build_command_center.py first")
    return json.loads(DATA.read_text(encoding="utf-8"))


def facts() -> dict:
    """Every headline number, with the ones that are arithmetic derived rather than stored."""
    d = _snapshot()
    recon, lineage = d["recon"], d["lineage"]

    merchants = recon["merchants"]
    active_mid_days = recon["mid_days"]
    # Both halves come from the export's own `truth` block, which Gold produced. They are cross-checked
    # against the total below rather than trusted individually, so a drift in either one fails loudly.
    assessed_mid_days = d["truth"]["assessed_mid_days"]
    in_transit_mid_days = d["truth"]["not_assessed_mid_days"]
    if assessed_mid_days + in_transit_mid_days != active_mid_days:
        raise SystemExit(f"merchant-day split does not reconcile: {assessed_mid_days} + "
                         f"{in_transit_mid_days} != {active_mid_days}")

    possible_mid_days = merchants * WINDOW_DAYS
    zero_trade_mid_days = possible_mid_days - active_mid_days

    return {
        # -- reconciliation ----------------------------------------------------------------
        "merchants": merchants,
        "window_days": WINDOW_DAYS,
        "possible_mid_days": possible_mid_days,
        "active_mid_days": active_mid_days,
        "assessed_mid_days": assessed_mid_days,
        "in_transit_mid_days": in_transit_mid_days,
        "zero_trade_mid_days": zero_trade_mid_days,
        "gross_captures_sar": recon["gross"],
        "bank_paid_sar": recon["bank"],
        "in_transit_sar": recon["transit"],
        "bank_variance_sar": recon["bank_variance"],
        "gl_variance_sar": recon["gl_variance"],
        "unclassified_events": recon["unclassified"],
        # -- lineage -----------------------------------------------------------------------
        "gold_columns_traced": lineage["covered"],
        # -- fixed repository facts ---------------------------------------------------------
        "adr_count": len(list((REPO / "docs" / "adr").glob("ADR-*.md"))),
        "invariant_count": 14,
        # The prior Fabric evidence run, kept because it is cited and must never be mistaken for current.
        "prior_fabric_gross_sar": "22390730.16",
    }


def main() -> int:
    f = facts()
    width = max(len(k) for k in f)
    for k, v in f.items():
        print(f"{k:<{width}}  {v}")
    print()
    print("The denominator, spelled out, because '2,121 assessed' invites 'out of what?':")
    print(f"  {f['merchants']} merchants x {f['window_days']} days = {f['possible_mid_days']:,} possible")
    print(f"  = {f['active_mid_days']:,} with activity "
          f"({f['assessed_mid_days']:,} assessed + {f['in_transit_mid_days']} in transit)")
    print(f"  + {f['zero_trade_mid_days']} with no trading")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
