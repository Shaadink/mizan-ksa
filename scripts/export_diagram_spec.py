r"""Write the 02 dataflow spec out as JSON, so the Remotion animation animates the same facts the SVG draws.

    .\.venv\Scripts\python.exe scripts\export_diagram_spec.py
    .\.venv\Scripts\python.exe scripts\export_diagram_spec.py d:\mizan-video\src\spec.json

**Why this exists.** The launch video needs an animated version of `02_dataflow_one_sale`, and Remotion is
React, which cannot import a Python module. The obvious move is to retype the five lanes into a TypeScript
file. That is the move that goes wrong: the day someone renames `slv.settlement_lines`, the SVG in the
README changes and the animation in the video does not, and nobody finds out because no test compares a
picture to a video.

So the lanes live once, at module level in `build_diagrams.py`, and this writes them out. The animation
reads the export. `tests/test_diagrams.py` checks the export matches the module, so the two cannot drift
without the suite going red.

The video project deliberately lives OUTSIDE this repository (`d:\mizan-video`). Remotion pulls in a
Chromium and several hundred megabytes of node_modules, and the repository is an engineering artifact
someone may read -- a video toolchain in it is noise. The spec crosses the boundary as this one JSON file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from build_diagrams import (  # noqa: E402
    BRZ,
    CRIT,
    CYAN,
    DATAFLOW_SUB,
    DATAFLOW_TITLE,
    DIM,
    EMERALD,
    GOLD,
    INK,
    LANES,
    LINE,
    MUTED,
    NIGHT,
    PANEL,
    SLV,
    SLVSUB,
    SPINE,
    VIOLET,
    WARN,
)

DEFAULT_OUT = REPO / "docs" / "diagrams" / "dataflow_spec.json"


def spec() -> dict:
    """The same five lanes `dataflow_one_sale()` draws, as plain JSON."""
    return {
        "_generated_by": "scripts/export_diagram_spec.py -- do not edit by hand",
        "title": DATAFLOW_TITLE,
        "subtitle": DATAFLOW_SUB,
        "palette": {"night": NIGHT, "panel": PANEL, "line": LINE, "ink": INK, "muted": MUTED,
                    "dim": DIM, "gold": GOLD, "emerald": EMERALD, "cyan": CYAN, "violet": VIOLET,
                    "crit": CRIT, "warn": WARN},
        "lanes": [{"name": name, "source": src, "accent": accent, "facts": list(facts),
                   "bronze": BRZ[i], "silver": SLV[i], "silver_note": SLVSUB[i],
                   # Lane 0 (the order) never reaches the spine. Stated as data so the animation
                   # cannot quietly draw the arrow the SVG refuses to draw.
                   "reaches_spine": i != 0}
                  for i, (name, src, accent, facts) in enumerate(LANES)],
        "spine": [{"label": lbl, "value": val, "accent": accent} for lbl, val, accent in SPINE],
        "verdicts": [{"label": "unexplained_bank_variance", "value": "0.00"},
                     {"label": "unexplained_gl_variance", "value": "0.00"},
                     {"label": "unclassified_events", "value": "0"}],
    }


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(spec(), indent=2, ensure_ascii=True) + "\n"
    out.write_text(text, encoding="utf-8")
    print(f"{out}  ({len(text):,} bytes, {len(spec()['lanes'])} lanes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
