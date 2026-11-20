"""Draw the Fabric Airflow DAG from the DAG's own edges, so the picture cannot disagree with the code.

    .\\.venv\\Scripts\\python.exe scripts\\render_dag_graph.py

Writes docs/artifacts/06_fabric_airflow_dag.svg. Open it in VS Code or any browser.

This is a *diagram*, not a screenshot: it is drawn from `dags/mizan_fabric_daily.py`'s `edges()` and the
timings recorded in docs/artifacts/10_fabric_run_evidence.json. docs/artifacts/06_airflow_dag.png is the
screenshot of the real Airflow UI, from the Docker stack. Keeping the two clearly apart matters, because one
is evidence of a run and the other is only an explanation of a shape.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "artifacts" / "06_fabric_airflow_dag.svg"

BOX_W, BOX_H, GAP_X, GAP_Y, PAD = 188, 62, 56, 26, 28
TITLE_H, FOOT_H = 64, 52

# Deliberately not the Command Center's palette: this is a plain technical drawing, and it has to stay
# legible when GitHub renders it on a white page and when VS Code shows it on a dark one. Every colour is
# chosen to pass contrast against BOTH backgrounds, so the SVG carries no background fill of its own.
INK, MUTED, LINE = "#1f2933", "#5b6b7c", "#8fa3b8"
FILL, STROKE, ACCENT = "#e8eef5", "#2f6f8f", "#0f5c7a"


def _load_dag_module():
    path = REPO / "dags" / "mizan_fabric_daily.py"
    spec = importlib.util.spec_from_file_location("mizan_fabric_daily", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mizan_fabric_daily"] = module
    spec.loader.exec_module(module)
    return module


def _seconds_by_step() -> dict[str, int]:
    evidence = json.loads((REPO / "docs" / "artifacts" / "10_fabric_run_evidence.json").read_text("utf-8"))
    return {k: v.get("seconds", 0) for k, v in evidence["notebook_jobs"].items()}


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def layout(chain: tuple[str, ...], fan_out: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    """Chain left to right on one row; the fan-out stacked in a column after it."""
    span = len(fan_out) * BOX_H + (len(fan_out) - 1) * GAP_Y
    row_y = TITLE_H + (span - BOX_H) // 2
    at = {step: (PAD + i * (BOX_W + GAP_X), row_y) for i, step in enumerate(chain)}
    x = PAD + len(chain) * (BOX_W + GAP_X)
    for i, step in enumerate(fan_out):
        at[step] = (x, TITLE_H + i * (BOX_H + GAP_Y))
    return at


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(module) -> str:
    at = layout(module.CHAIN, module.FAN_OUT)
    secs = _seconds_by_step()
    width = max(x for x, _ in at.values()) + BOX_W + PAD
    height = max(y for _, y in at.values()) + BOX_H + FOOT_H
    total = sum(secs.get(s, 0) for s in module.STEP_ORDER)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" font-family="Segoe UI, Inter, system-ui, sans-serif" role="img" '
        f'aria-label="mizan_fabric_daily: {" then ".join(module.STEP_ORDER)}">',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker></defs>',
        f'<text x="{PAD}" y="26" font-size="17" font-weight="600" fill="{INK}">mizan_fabric_daily</text>',
        f'<text x="{PAD}" y="46" font-size="12.5" fill="{MUTED}">Apache Airflow job AF_MIZAN in Microsoft '
        f'Fabric &#183; 03:00 Asia/Riyadh &#183; one run at a time</text>',
    ]

    for upstream, downstream in module.edges():
        ux, uy = at[upstream]
        dx, dy = at[downstream]
        x1, y1, x2, y2 = ux + BOX_W, uy + BOX_H // 2, dx, dy + BOX_H // 2
        mid = x1 + (x2 - x1) / 2
        path = (f"M{x1},{y1} L{x2 - 8},{y2}" if y1 == y2 else
                f"M{x1},{y1} C{mid},{y1} {mid},{y2} {x2 - 8},{y2}")
        parts.append(f'<path d="{path}" fill="none" stroke="{LINE}" stroke-width="1.6" marker-end="url(#a)"/>')

    for step in module.STEP_ORDER:
        x, y = at[step]
        parts += [
            f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="9" fill="{FILL}" '
            f'stroke="{STROKE}" stroke-width="1.4"/>',
            f'<text x="{x + 14}" y="{y + 26}" font-size="14" font-weight="600" fill="{ACCENT}" '
            f'font-family="Consolas, monospace">{_esc(step)}</text>',
            f'<text x="{x + 14}" y="{y + 45}" font-size="11.5" fill="{MUTED}">'
            f'nb_mizan_step &#183; {_mmss(secs.get(step, 0))}</text>',
        ]

    parts += [
        f'<text x="{PAD}" y="{height - 26}" font-size="11.5" fill="{MUTED}">Drawn from the DAG\'s own '
        f'edges() and the 2026-11-19 run ({_mmss(total)} across {len(module.STEP_ORDER)} notebook jobs). '
        f'Not a screenshot: 06_airflow_dag.png is the real Airflow UI.</text>',
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def main() -> None:
    module = _load_dag_module()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(module), encoding="utf-8", newline="\n")
    print(f"{OUT.relative_to(REPO).as_posix()}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
