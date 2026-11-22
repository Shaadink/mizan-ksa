r"""Capture the eight README demo screenshots from the standalone Command Center.

    .\.venv\Scripts\python.exe scripts\demo_shots.py

**What this can and cannot do, stated up front because it matters.**

The README asks for these eight shots "from the Fabric App with the green Live label visible". This script
drives the **standalone** copy (`command_center/index.html`) instead, because the Fabric App is behind a
tenant sign-in that a script has no business holding.

Everything in the scenes is the same -- same code, same scenes, same figures exported from the same Gold
tables. The one visible difference is the provenance label: the standalone says "exported Gold snapshot"
where the Fabric App says "Live". That label is the honest part and must not be edited out of the images.

So: these are real screenshots of the real thing, suitable for the README and for a video. If a shot is
needed that specifically evidences *live DAX against the semantic model*, it has to be taken by hand from
the Fabric App. The filenames are the same either way, so a hand-taken shot simply overwrites one of these.

Keyboard shortcuts drive the page the same way a presenter would: `P` presenter mode, `1`-`9` scenes,
`B` break a halala, `L` Arabic.
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "command_center" / "index.html"
OUT = REPO / "docs" / "artifacts" / "demo"

# (filename, what it is, how to get there). `keys` are pressed in order; `wait` lets animation settle --
# the hero scale physically swings before it settles, and a shot taken mid-swing shows an UNBALANCED
# scale, which would be a photograph of the opposite of the claim.
SHOTS = (
    ("01_hero.png", "the scale settles at SAR 0.00 across 2,121 assessed merchant-days",
     {"keys": ["p"], "wait": 7000}),
    ("02_city_jeddah.png", "heatmap and KPIs recomputed for one city",
     {"keys": ["p", "2"], "wait": 3500}),
    ("03_merchant_day_drill.png", "one merchant-day, every leg at once",
     {"keys": ["p", "4"], "wait": 3500}),
    ("04_break_a_halala.png", "a planted break tilts the scale; the candidate run refuses to publish",
     {"keys": ["p", "b"], "wait": 5000}),
    ("05_zatca_chain.png", "EGS cards, the outcome bar, the one rejection kept in the chain",
     {"keys": ["p", "5"], "wait": 3500}),
    ("06_store_map.png", "stores by city, coloured by reconciliation status",
     {"keys": ["p", "7"], "wait": 3500}),
    ("07_arabic_rtl.png", "Arabic right-to-left, numbers and IDs still left-to-right",
     {"keys": ["p", "l"], "wait": 4000}),
    ("08_life_cycle.png", "sources to Gold to the Control Tower, each box linked to its proof",
     {"keys": ["p", "9"], "wait": 3500}),
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--scale", type=float, default=1.5, help="device scale factor; 1.5 is retina-ish")
    ap.add_argument("--only", default=None, help="substring of one filename, to redo a single shot")
    args = ap.parse_args()

    if not PAGE.exists():
        raise SystemExit(f"{PAGE} not built -- run scripts/build_command_center.py first")
    OUT.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    written = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, what, how in SHOTS:
            if args.only and args.only not in name:
                continue
            # A fresh page per shot. Sharing one page would leak state -- a filter set for the city shot
            # would still be applied two shots later, and the images would quietly disagree with each other.
            page = browser.new_page(viewport={"width": args.width, "height": args.height},
                                    device_scale_factor=args.scale)
            page.goto(PAGE.resolve().as_uri())
            page.wait_for_timeout(2500)          # three.js hero and the first render
            for key in how["keys"]:
                page.keyboard.press(key)
                page.wait_for_timeout(700)
            page.wait_for_timeout(how["wait"])
            out = OUT / name
            page.screenshot(path=str(out), full_page=False)
            page.close()
            written.append(out)
            print(f"  {name:<28} {what}")
        browser.close()

    print(f"\nwrote {len(written)} screenshots to {OUT.relative_to(REPO)}")
    print("Provenance: these are the STANDALONE page, which labels itself 'exported Gold snapshot'.")
    print("For a shot that evidences live DAX, retake it from the Fabric App over the same filename.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
