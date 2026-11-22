r"""Build the six engineering diagrams in docs/diagrams/ as SVG.

    .\.venv\Scripts\python.exe scripts\build_diagrams.py

Why a generator rather than six hand-drawn files. A diagram is a claim about the system, and a drawing
drifts from the system the moment either changes. These are laid out from declarative specs in this file,
and two of them -- the dbt lineage and the schema map -- are built from real metadata (`dbt/target/
manifest.json` and the table names the Spark layer actually writes), so they cannot describe a shape the
code does not have.

Dark palette, deliberately the Command Center's own, so a diagram cut into the demo video does not look
like it came from a different project.

Output, 16:9 where it can be, for video:
  01_architecture.svg           the whole platform on one page, data plane and control plane
  02_dataflow_one_sale.svg      one sale through seven source systems into the three-way spine
  03_schema_map.svg             LH_MIZAN's eight schemas and WH_MIZAN's gld, with the key contract
  04_zatca_state_machine.svg    the outbox state machine, every edge labelled with its HTTP status
  05_reconciliation_spine.svg   why it is a UNION key spine and not a LEFT JOIN
  06_dbt_lineage.svg            generated from dbt's manifest: 7 Gold models over their Silver sources
"""

from __future__ import annotations

import html
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "diagrams"
MANIFEST = REPO / "dbt" / "target" / "manifest.json"

# The Command Center's palette, so diagrams and app footage cut together.
NIGHT, PANEL, LINE = "#060b16", "#0a1324", "#1e2b45"
INK, MUTED, DIM = "#e8eef7", "#a9b6c9", "#6b7a90"
GOLD, EMERALD, CYAN, VIOLET, CRIT, WARN = "#d9b25f", "#2fbf8f", "#5cc8ff", "#9b8cff", "#ff5d63", "#f0a73c"

MONO = "ui-monospace, 'Cascadia Mono', 'Cascadia Code', Consolas, 'Courier New', monospace"
SANS = "'Segoe UI', Inter, system-ui, -apple-system, sans-serif"


# ----------------------------------------------------------------------------- tiny SVG writer
class Svg:
    def __init__(self, w: int, h: int, title: str, sub: str) -> None:
        self.w, self.h, self.parts = w, h, []
        self.parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="{SANS}" role="img" aria-label="{html.escape(title)}">'
            f"<title>{html.escape(title)}</title>"
            "<defs>"
            f'<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{DIM}"/></marker>'
            f'<marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{GOLD}"/></marker>'
            f'<marker id="ae" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{EMERALD}"/></marker>'
            f'<marker id="ac" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{CRIT}"/></marker>'
            "</defs>"
            f'<rect width="{w}" height="{h}" fill="{NIGHT}"/>')
        self.text(40, 54, title, size=27, weight=700, fill=INK)
        if sub:
            self.text(40, 82, sub, size=14, fill=MUTED)

    # -- primitives
    def text(self, x, y, s, *, size=13, fill=INK, weight=400, mono=False, anchor="start", opacity=1.0):
        f = f' font-family="{MONO}"' if mono else ""
        o = f' opacity="{opacity}"' if opacity != 1.0 else ""
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
                          f'fill="{fill}" text-anchor="{anchor}"{f}{o}>{html.escape(str(s))}</text>')

    def box(self, x, y, w, h, *, stroke=LINE, fill=PANEL, r=10, dash=None, sw=1):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" '
                          f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def line(self, x1, y1, x2, y2, *, stroke=DIM, head="a", dash=None, sw=1.4):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#{head})"' if head else ""
        self.parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
                          f'stroke-width="{sw}"{d}{m}/>')

    def path(self, d, *, stroke=DIM, head="a", dash=None, sw=1.4, fill="none"):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#{head})"' if head else ""
        self.parts.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{da}{m}/>')

    # -- composites
    def panel(self, x, y, w, h, title, *, accent=LINE, tag=""):
        self.box(x, y, w, h, stroke=accent)
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="3" rx="1.5" fill="{accent}"/>')
        self.text(x + 14, y + 26, title, size=12.5, weight=700, fill=accent, mono=True)
        if tag:
            self.text(x + w - 14, y + 26, tag, size=10.5, fill=DIM, mono=True, anchor="end")

    def node(self, x, y, w, h, label, sub="", *, accent=LINE, fill=PANEL, mono=True, size=12.5):
        self.box(x, y, w, h, stroke=accent, fill=fill, r=8)
        cy = y + h / 2 + (0 if not sub else -6)
        self.text(x + w / 2, cy + 4, label, size=size, weight=600, fill=INK, mono=mono, anchor="middle")
        if sub:
            self.text(x + w / 2, cy + 20, sub, size=10.5, fill=MUTED, mono=True, anchor="middle")

    def foot(self, note):
        self.text(40, self.h - 22, note, size=10.5, fill=DIM, mono=True)

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text("".join(self.parts) + "</svg>", encoding="utf-8", newline="\n")
        print(f"  docs/diagrams/{name}")


STAMP = "MIZAN-KSA | synthetic data | generated by scripts/build_diagrams.py -- do not edit the SVG by hand"


# ----------------------------------------------------------------------------- 01 architecture
def architecture() -> None:
    s = Svg(1680, 950, "MIZAN-KSA architecture",
            "Data plane on Microsoft Fabric. Control plane beside it. Every box below is a real item, "
            "not a placeholder.")
    y0, colw, gap = 118, 290, 28
    xs = [40 + i * (colw + gap) for i in range(5)]
    heads = [("SOURCE SYSTEMS", DIM, "CSV / JSONL / stream"),
             ("BRONZE  LH_MIZAN.brz", GOLD, "Delta, append-only"),
             ("SILVER  LH_MIZAN.slv", CYAN, "Delta, typed + conformed"),
             ("GOLD  WH_MIZAN.gld", EMERALD, "Warehouse, tables"),
             ("CONSUMPTION", VIOLET, "Direct Lake / DAX")]
    ph = 470
    for x, (t, c, tag) in zip(xs, heads, strict=True):
        s.panel(x, y0, colw, ph, t, accent=c, tag="")
        s.text(x + 14, y0 + 44, tag, size=10, fill=DIM, mono=True)

    rows = [
        ["commerce_events.csv", "payment_events.csv", "NAJDACQ_SETTLEMENT_*.csv", "erp_gl_acdoca.csv",
         "crm_pos_cp1256.csv", "crm_ecom_utf8.csv", "spl_address_observations.csv",
         "zatca invoice_requests.jsonl", "ES_MIZAN  (Eventstream)"],
        ["commerce_events_raw", "payment_events_raw", "settlement_batches_raw", "erp_gl_raw",
         "crm_party_raw", "spl_address_raw", "zatca_invoices_raw", "", "PII encrypted AT the write"],
        ["payment_lifecycle", "settlement_lines", "erp_gl_journal_lines", "zatca_invoice_documents",
         "golden_party_scd2", "identifier_registry", "address_observations", "entity_merge_ledger",
         "quarantine.*  (4 tables)"],
        ["fact_merchant_settlement_recon", "fact_zatca_clearance_ledger", "fact_payment_method_daily",
         "fact_merchant_dispute_monitor", "dim_party_golden", "dim_date_saudi", "mart_ndmo_scorecard",
         "", "7 models, 89 tests, 3 seeds"],
        ["MIZAN Control Tower Model", "Power BI report", "Command Center (Fabric App)",
         "EH_MIZAN  (Eventhouse / KQL)", "ai.policy_chunks  (governed RAG)", "", "", "",
         "94/94 Gold columns traced"]]
    accents = [DIM, GOLD, CYAN, EMERALD, VIOLET]
    for x, items, c in zip(xs, rows, accents, strict=True):
        yy = y0 + 62
        for it in items:
            if not it:
                yy += 10
                continue
            last = it.startswith(("PII ", "7 models", "94/94", "quarantine")) or it.startswith("ES_MIZAN")
            s.box(x + 12, yy, colw - 24, 34, stroke=LINE if not last else c, r=7,
                  fill="#0d1729" if not last else "#0a1324", dash="3 3" if last else None)
            s.text(x + 22, yy + 22, it, size=10.5, fill=INK if not last else c, mono=True)
            yy += 41

    for i in range(4):
        s.line(xs[i] + colw + 4, y0 + ph / 2, xs[i + 1] - 6, y0 + ph / 2,
               stroke=[GOLD, CYAN, EMERALD, VIOLET][i], head=["ag", "a", "ae", "a"][i], sw=1.8)

    cy = y0 + ph + 46
    s.panel(40, cy, 1600, 170, "CONTROL PLANE", accent=WARN, tag="runs the data plane, proves the data plane")
    ctl = [("Apache Airflow", "AF_MIZAN in Fabric; also Docker locally", WARN),
           ("Docker", "docker-compose.airflow.yml / .skew.yml", WARN),
           ("dbt-fabric", "dbt build = 99 nodes: 7 models, 89 tests, 3 seeds", EMERALD),
           ("OpenLineage", "emitted per run -> Marquez", CYAN),
           ("pytest", "444 tests + 184 Fabric App tests", VIOLET),
           ("GitHub Actions", "lint, PySpark suite, app suite, every push", GOLD)]
    bw = (1600 - 24 - 5 * 14) / 6
    for i, (n, d, c) in enumerate(ctl):
        x = 52 + i * (bw + 14)
        s.box(x, cy + 54, bw, 92, stroke=c, r=9)
        s.text(x + bw / 2, cy + 86, n, size=13, weight=700, fill=c, anchor="middle")
        for j, part in enumerate(_wrap(d, 30)):
            s.text(x + bw / 2, cy + 106 + j * 14, part, size=9.5, fill=MUTED, mono=True, anchor="middle")
        s.line(x + bw / 2, cy + 52, x + bw / 2, y0 + ph + 8, stroke=c, head="a", dash="4 4", sw=1)

    s.foot(STAMP)
    s.save("01_architecture.svg")


def _wrap(text: str, width: int) -> list[str]:
    out, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width and cur:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    return out


# ----------------------------------------------------------------------------- 02 one sale
def dataflow_one_sale() -> None:
    s = Svg(1680, 960, "One sale, five systems, one answer",
            "The same SAR 138.00 purchase as each system records it -- and the three legs that must agree "
            "to the halala.")
    lanes = [("THE TILL", "commerce_events.csv", GOLD,
              ["ORDER_PLACED", "order_id ORD-004112", "amount_sar 138.00", "event_ts_utc 09:14:22Z"]),
             ("THE CARD", "payment_events.csv", CYAN,
              ["CAPTURE  MADA", "payment_event_id PE-88301", "amount_sar 138.00", "positive; sign is the type"]),
             ("THE TAX AUTHORITY", "zatca/invoice_requests.jsonl", VIOLET,
              ["REPORTING (simplified)", "invoice_uuid 0ec9539b...", "ICV 103, PIH = prev hash",
               "total_incl_vat 138.00"]),
             ("THE BANK", "NAJDACQ_SETTLEMENT_20260215.csv", EMERALD,
              ["PURCHASE  CR", "payment_event_id PE-88301", "gross 138.00  mdr 0.83",
               "vat_on_fee 0.12  net 137.05"]),
             ("THE LEDGER", "erp_gl_acdoca.csv", WARN,
              ["BELNR 4900031881", "RACCT card clearing  DRCRK S", "HSL 138.00", "BUDAT 20260213"])]
    y = 130
    lx, lw = 40, 300
    bx, bw = 372, 270
    sx, sw2 = 672, 250
    for name, src, c, facts in lanes:
        s.box(lx, y, lw, 118, stroke=c, r=10)
        s.text(lx + 14, y + 26, name, size=12, weight=700, fill=c)
        s.text(lx + 14, y + 44, src, size=9.5, fill=DIM, mono=True)
        for i, f in enumerate(facts):
            s.text(lx + 14, y + 66 + i * 15, f, size=10, fill=INK if i < 3 else MUTED, mono=True)
        y += 140

    y = 130
    brz = ["brz.commerce_events_raw", "brz.payment_events_raw", "brz.zatca_invoices_raw",
           "brz.settlement_batches_raw", "brz.erp_gl_raw"]
    # The order is NOT a leg of the money spine. It stays in Bronze and is read by the PDPL
    # right-of-access path and the governed AI index. Drawing it into payment_lifecycle would be a
    # picture of a join the code does not do.
    slv = ["(stays in Bronze: PDPL subject access + ai index)", "slv.payment_lifecycle",
           "slv.zatca_invoice_documents", "slv.settlement_lines", "slv.erp_gl_journal_lines"]
    slvsub = ["not a leg of the money spine", "typed, deduped, conformed", "typed, deduped, conformed",
              "typed, deduped, conformed", "typed, deduped, conformed"]
    for i, (_name, _src, c, _f) in enumerate(lanes):
        s.line(lx + lw + 4, y + 59, bx - 6, y + 59, stroke=c, head="a")
        s.node(bx, y + 34, bw, 50, brz[i], "append-only, PII encrypted here", accent=c)
        s.line(bx + bw + 4, y + 59, sx - 6, y + 59, stroke=c, head="a")
        s.node(sx, y + 34, sw2, 50, slv[i], slvsub[i], accent=c,
               size=9.5 if i == 0 else 12.5, fill="#0a1324" if i else "#0d1018")
        y += 140

    # the spine
    gx, gy, gw, gh = 992, 170, 300, 460
    s.panel(gx, gy, gw, gh, "THE THREE-WAY SPINE", accent=INK,
            tag="")
    s.text(gx + 14, gy + 46, "gld.fact_merchant_settlement_recon", size=10.5, fill=EMERALD, mono=True)
    s.text(gx + 14, gy + 70, "UNION of keys from all three legs.", size=10.5, fill=MUTED, mono=True)
    s.text(gx + 14, gy + 85, "No LEFT JOIN can drop a row.", size=10.5, fill=MUTED, mono=True)
    eq = [("payments", "138.00", CYAN), ("- fees from the bank file", "0.95", EMERALD),
          ("= expected net payable", "137.05", INK), ("bank paid", "137.05", EMERALD),
          ("GL card clearing", "138.00", WARN)]
    yy = gy + 112
    for lbl, val, c in eq:
        s.text(gx + 14, yy, lbl, size=10.5, fill=c, mono=True)
        s.text(gx + gw - 14, yy, val, size=10.5, fill=INK, mono=True, anchor="end")
        yy += 20
    s.line(gx + 14, yy, gx + gw - 14, yy, stroke=LINE, head=None)
    yy += 24
    for lbl, c in (("unexplained_bank_variance  0.00", EMERALD), ("unexplained_gl_variance    0.00", EMERALD),
                   ("unclassified_events        0", EMERALD)):
        s.text(gx + 14, yy, lbl, size=11, weight=700, fill=c, mono=True)
        yy += 22
    s.text(gx + 14, yy + 10, "Both must be 0.00 or the", size=10.5, fill=CRIT, mono=True)
    s.text(gx + 14, yy + 25, "dbt build halts and nothing", size=10.5, fill=CRIT, mono=True)
    s.text(gx + 14, yy + 40, "is published.", size=10.5, fill=CRIT, mono=True)
    s.text(gx + 14, yy + 70, "A day whose bank file has not", size=10, fill=WARN, mono=True)
    s.text(gx + 14, yy + 84, "arrived becomes an IN_TRANSIT", size=10, fill=WARN, mono=True)
    s.text(gx + 14, yy + 98, "expectation row -- never balanced.", size=10, fill=WARN, mono=True)

    for i in (1, 3, 4):
        s.path(f"M {sx + sw2 + 4} {130 + i * 140 + 59} C {gx - 40} {130 + i * 140 + 59}, "
               f"{gx - 40} {gy + gh / 2}, {gx - 6} {gy + gh / 2}",
               stroke=lanes[i][2], head="a")
    s.path(f"M {sx + sw2 + 4} {130 + 2 * 140 + 59} C {940} {130 + 2 * 140 + 59}, "
           f"{940} {gy + gh + 85}, {1314} {gy + gh + 85}", stroke=VIOLET, head="a")
    s.node(1320, gy + gh + 60, 300, 50, "gld.fact_zatca_clearance_ledger",
           "one GL posting per invoice_uuid", accent=VIOLET)

    s.node(1320, gy, 300, 50, "MIZAN Control Tower Model", "semantic model, Direct Lake", accent=INK)
    s.node(1320, gy + 70, 300, 50, "Command Center (Fabric App)", "live DAX, EN + AR", accent=INK)
    s.line(gx + gw + 4, gy + 25, 1314, gy + 25, stroke=EMERALD, head="ae")
    s.line(gx + gw + 4, gy + 95, 1314, gy + 95, stroke=EMERALD, head="ae")

    s.foot(STAMP + " | figures illustrative of one row; totals are in the Gold tables")
    s.save("02_dataflow_one_sale.svg")


# The eight lakehouse schemas and their tables, at module level so tests/test_diagrams.py can
# check every name against what src/mizan/spark/*.py actually writes.
LAKEHOUSE_TABLES = [
    ("brz", GOLD, "raw, append-only",
     ["commerce_events_raw", "payment_events_raw", "settlement_batches_raw", "erp_gl_raw",
      "crm_party_raw", "spl_address_raw", "zatca_invoices_raw"]),
    ("ctl", CYAN, "control, idempotency",
     ["applied_event_ledger", "ingestion_watermarks", "invoice_outbox", "egs_chain_state",
      "deletion_tombstones"]),
    ("slv", CYAN, "typed, conformed",
     ["payment_lifecycle", "settlement_lines", "erp_gl_journal_lines", "zatca_invoice_documents",
      "golden_party_scd2", "identifier_registry", "entity_merge_ledger", "address_observations"]),
    ("quarantine", CRIT, "never an else branch",
     ["schema_rejections", "settlement_breaks", "zatca_chain_violations", "mdm_match_conflicts"]),
    ("security", CRIT, "PDPL, zero retention",
     ["subject_token_map", "pii_vault_metadata"]),
    ("audit", WARN, "write-once evidence",
     ["zatca_chain_journal", "benchmarks"]),
    ("meta", VIOLET, "catalogue",
     ["column_classification"]),
    ("ai", VIOLET, "governed retrieval",
     ["policy_chunks", "agent_audit_log"]),
]


# ----------------------------------------------------------------------------- 03 schema map
def schema_map() -> None:
    s = Svg(1680, 880, "LH_MIZAN and WH_MIZAN: the schemas, and what guards each one",
            "Eight schemas in the lakehouse, one in the warehouse. Names are frozen by the blueprint; "
            "these are the tables the Spark layer actually writes.")
    schemas = LAKEHOUSE_TABLES
    x, y = 40, 132
    cols, cw, ch = 4, 384, 186
    s.text(40, 112, "LH_MIZAN   (OneLake Delta lakehouse)", size=13, weight=700, fill=INK, mono=True)
    for i, (name, c, note, tables) in enumerate(schemas):
        cx = x + (i % cols) * (cw + 16)
        cy = y + (i // cols) * (ch + 16)
        s.panel(cx, cy, cw, ch if i < cols else 126, name, accent=c, tag=note)
        for j, t in enumerate(tables):
            s.text(cx + 16, cy + 50 + j * 17, t, size=10.5, fill=MUTED, mono=True)

    wy = y + ch + 16 + 126 + 26
    s.text(40, wy - 10, "WH_MIZAN   (Fabric Warehouse, T-SQL)", size=13, weight=700, fill=INK, mono=True)
    s.panel(40, wy, 784, 196, "gld", accent=EMERALD, tag="dbt materialized as TABLES, never views")
    gld = ["fact_merchant_settlement_recon  (incremental, delete+insert)",
           "fact_zatca_clearance_ledger", "fact_payment_method_daily",
           "fact_merchant_dispute_monitor", "dim_party_golden", "dim_date_saudi",
           "mart_ndmo_scorecard"]
    for j, t in enumerate(gld):
        s.text(56, wy + 50 + j * 17, t, size=10.5, fill=MUTED, mono=True)

    s.panel(840, wy, 800, 196, "THE RULES THAT ARE NOT NEGOTIABLE", accent=INK, tag="blueprint 8 and 12")
    rules = [("Money", "Decimal in Python, DECIMAL(18,2) in SQL. Never float.", EMERALD),
             ("Sign", "amounts positive; event_type carries CAPTURE/REFUND/CHARGEBACK.", EMERALD),
             ("Fees", "MDR and VAT-on-fee come from the bank file, at the bank's grain.", EMERALD),
             ("Strings", "VARCHAR(n) sized in BYTES. No NVARCHAR, DATETIME or MONEY.", CYAN),
             ("Enums", "UPPERCASE, accepted_values tested. Unknown -> raise or quarantine.", CYAN),
             ("Time", "Asia/Riyadh, Spark session TZ included. Settlement date from the bank.", GOLD),
             ("PII", "encrypted at the Bronze write: HMAC token + AES-256-GCM per-subject DEK.", CRIT)]
    for j, (k, v, c) in enumerate(rules):
        s.text(856, wy + 50 + j * 19, f"{k:<8}", size=10.5, fill=c, weight=700, mono=True)
        s.text(856 + 72, wy + 50 + j * 19, v, size=10.5, fill=MUTED, mono=True)

    s.foot(STAMP + " | table names read from src/mizan/spark/*.py")
    s.save("03_schema_map.svg")


# ----------------------------------------------------------------------------- 04 state machine
def zatca_state_machine() -> None:
    s = Svg(1680, 980, "ZATCA Phase-2 submission: the outbox state machine",
            "SUBMITTING is persisted BEFORE the HTTP call. Only 200, 202, 400, 401 and 403 are definitive. "
            "Everything else keeps the same UUID and the same signed bytes.")
    nodes = {
        "PENDING": (70, 420, DIM, "row in ctl.invoice_outbox"),
        "SIGNED": (350, 420, CYAN, "invoice_hash computed ONCE"),
        "SUBMITTING": (630, 420, WARN, "persisted BEFORE the call"),
        "CLEARED": (900, 170, EMERALD, "200, clearance API"),
        "REPORTED": (900, 260, EMERALD, "200, reporting API"),
        "ACCEPTED_WITH_WARNINGS": (900, 350, EMERALD, "202"),
        "CONFIRMED_REJECTION": (900, 470, CRIT, "400 -- stays in the chain"),
        "AUTH_HOLD": (900, 580, CRIT, "401 / 403 -- renew CSID"),
        "UNKNOWN_OUTCOME": (900, 690, WARN, "5xx, timeout, 409, kill -9"),
    }
    w, h = 240, 56
    for name, (x, y, c, sub) in nodes.items():
        s.node(x, y, w, h, name, sub, accent=c, size=11.5 if len(name) > 18 else 12.5)

    s.line(70 + w + 4, 448, 350 - 6, 448, stroke=CYAN, head="a")
    s.line(350 + w + 4, 448, 630 - 6, 448, stroke=WARN, head="a")
    edges = [("CLEARED", "200", EMERALD, "ae"), ("REPORTED", "200", EMERALD, "ae"),
             ("ACCEPTED_WITH_WARNINGS", "202", EMERALD, "ae"),
             ("CONFIRMED_REJECTION", "400", CRIT, "ac"), ("AUTH_HOLD", "401 / 403", CRIT, "ac"),
             ("UNKNOWN_OUTCOME", "anything else", WARN, "a")]
    for name, label, c, head in edges:
        x, y, _c, _s = nodes[name]
        s.path(f"M {630 + w + 4} 448 C {820} 448, {820} {y + h / 2}, {x - 6} {y + h / 2}",
               stroke=c, head=head)
        s.text(x - 16, y + 18, label, size=10.5, fill=c, mono=True, anchor="end")

    # retry loops
    s.path(f"M {900 - 6} {690 + 28} C {780} {760}, {700} {740}, {690} {420 + h + 6}",
           stroke=WARN, head="a", dash="5 4")
    s.text(300, 700, "retry the IDENTICAL UUID and the IDENTICAL signed bytes. Never a new ICV.",
           size=11.5, fill=WARN, mono=True)
    s.path(f"M {900 - 6} {580 + 28} C {830} {630}, {780} {620}, {766} {420 + h + 6}",
           stroke=CRIT, head="a", dash="5 4")
    s.text(300, 726, "AUTH_HOLD renews the CSID first, then resends the same bytes.",
           size=11.5, fill=CRIT, mono=True)

    s.panel(70, 790, 1570, 150, "THE THREE RULES THIS SHAPE EXISTS TO ENFORCE", accent=INK)
    for i, t in enumerate([
            "1. A worker killed in SUBMITTING recovers to UNKNOWN_OUTCOME, not to a new attempt.",
            "   The tax authority may already hold the document; a new UUID would duplicate it.",
            "2. invoice_hash is computed once at signing and becomes the next PIH -- whatever",
            "   ZATCA answers. A rejection stays in the chain; the fix is a NEW document, new ICV.",
            "3. B2C (reporting) posts to the GL at sale. B2B (clearance) posts after clearance.",
            "   Idempotency key = invoice_uuid, so accounting_postings == 1, always."]):
        s.text(86, 838 + (i // 2) * 34 + (i % 2) * 16, t, size=11,
               fill=MUTED if i % 2 else INK, mono=True)

    s.panel(1200, 170, 440, 560, "WHAT A DEFINITIVE ANSWER MEANS", accent=GOLD)
    for i, t in enumerate([
            "Definitive:   200  202  400  401  403",
            "Not definitive: everything else",
            "",
            "A 5xx, a gateway error, a 409 or a socket",
            "timeout tells you nothing about whether",
            "ZATCA processed the document. The only",
            "safe move is to send the same bytes again.",
            "",
            "HTTP 303 is special: it means clearance is",
            "deactivated for this taxpayer. The document",
            "is re-sent to the REPORTING endpoint, same",
            "UUID, same bytes, and a 200 there is",
            "REPORTED -- which counts as acceptance for",
            "a document that was issued for clearance.",
            "",
            "Genesis PIH = base64(hex(sha256(\"0\")))",
            "            = NWZlY2Vi...OQ==",
            "",
            "Not base64 of the raw digest. That one",
            "mistake breaks every chain after it.",
            "",
            "TLV length is the UTF-8 BYTE length.",
            "Tags 1-7 are text; tags 8-9 are raw bytes."]):
        c = GOLD if t.startswith(("Definitive", "Genesis", "TLV", "HTTP 303")) else MUTED
        s.text(1216, 228 + i * 21, t, size=10.5, fill=c, mono=True)

    s.foot(STAMP + " | states read from src/mizan/clearance/tlv_qr_and_state_machine.py")
    s.save("04_zatca_state_machine.svg")


# ----------------------------------------------------------------------------- 05 recon spine
def reconciliation_spine() -> None:
    s = Svg(1680, 900, "Why reconciliation is a key spine and not a join",
            "A LEFT JOIN answers 'what matched'. A finance team needs 'what is missing', which is a "
            "different question and a different shape.")
    legs = [("slv.payment_lifecycle", CYAN, "what the till captured",
             ["merchant_id", "business_date_ksa", "SUM(gross_captures_sar)", "SUM(refunds_and_disputes)"]),
            ("slv.settlement_lines", EMERALD, "what the bank paid",
             ["merchant_id", "settlement_for_date_ksa", "SUM(net_amount)", "mdr_fee + vat_on_fee"]),
            ("slv.erp_gl_journal_lines", WARN, "what the ledger says",
             ["merchant_id", "posting_date_ksa", "SUM(HSL) WHERE role =", "  CARD_CLEARING"])]
    y = 140
    for name, c, note, cols in legs:
        s.panel(40, y, 360, 180, name, accent=c, tag="")
        s.text(54, y + 46, note, size=10.5, fill=DIM, mono=True)
        for i, col in enumerate(cols):
            s.text(54, y + 72 + i * 18, col, size=10.5, fill=MUTED, mono=True)
        s.path(f"M 404 {y + 90} C 470 {y + 90}, 470 420, 516 420", stroke=c, head="a")
        y += 200

    s.panel(520, 300, 380, 240, "THE KEY SPINE", accent=INK, tag="UNION, not JOIN")
    for i, t in enumerate([
            "SELECT merchant_id, business_date_ksa",
            "FROM payments",
            "UNION",
            "SELECT merchant_id, settlement_for_date_ksa",
            "FROM settlement",
            "UNION",
            "SELECT merchant_id, posting_date_ksa",
            "FROM gl"]):
        s.text(536, 340 + i * 19, t, size=11, fill=CYAN if t.startswith("UNION") else MUTED, mono=True)
    s.text(536, 508, "Every key any leg has ever seen.", size=10.5, fill=INK, mono=True)
    s.text(536, 524, "A row missing from two legs still exists.", size=10.5, fill=INK, mono=True)

    s.line(904, 420, 946, 420, stroke=INK, head="a")
    s.panel(950, 170, 400, 500, "gld.fact_merchant_settlement_recon", accent=EMERALD,
            tag="one row per merchant-day")
    rows = [("gross_captures_sar", INK), ("refunds_and_disputes_sar", INK), ("acquirer_fees_sar", INK),
            ("= expected_net_payable_sar", EMERALD), ("", None),
            ("bank_paid_sar", INK), ("in_transit_sar", WARN), ("quarantined_sar", CRIT),
            ("", None),
            ("unexplained_bank_variance_sar", EMERALD), ("unexplained_gl_variance_sar", EMERALD),
            ("unclassified_events", EMERALD), ("", None),
            ("settlement_status", MUTED), ("  ASSESSED / IN_TRANSIT /", MUTED),
            ("  QUARANTINED", MUTED)]
    yy = 212
    for t, c in rows:
        if not t:
            yy += 8
            continue
        s.text(966, yy, t, size=10.5, fill=c, mono=True, weight=700 if c == EMERALD else 400)
        yy += 19

    s.panel(1380, 170, 260, 240, "THE INVARIANT", accent=CRIT)
    for i, t in enumerate([
            "expected_net =", "    bank_paid", "  + in_transit", "  + quarantined", "",
            "bank variance  0.00", "GL variance    0.00", "",
            "Both, or the dbt", "circuit breaker fails", "and the run is not", "published."]):
        c = CRIT if "variance" in t or "published" in t else MUTED
        s.text(1396, 206 + i * 18, t, size=10.5, fill=c, mono=True)

    s.panel(1380, 430, 260, 240, "IN_TRANSIT", accent=WARN)
    for i, t in enumerate([
            "A merchant-day whose", "bank file has not", "arrived does not", "silently disappear and",
            "is not called balanced.", "", "It gets an expectation", "row with status",
            "IN_TRANSIT, and it is", "counted separately:", "2,121 assessed,", "112 still waiting."]):
        s.text(1396, 466 + i * 18, t, size=10.5, fill=WARN if "IN_TRANSIT" in t or "112" in t else MUTED,
               mono=True)

    s.panel(40, 740, 1600, 110, "WHAT A LEFT JOIN WOULD HAVE DONE", accent=CRIT)
    for i, t in enumerate([
            "LEFT JOIN payments -> settlement silently drops a bank line for a payment the till never",
            "recorded -- exactly the row a fraud or a mis-keyed refund produces. The total still balances,",
            "because the missing money was never in the sum. That is the failure mode this shape removes."]):
        s.text(56, 796 + i * 18, t, size=11, fill=MUTED if i else CRIT, mono=True)

    s.foot(STAMP)
    s.save("05_reconciliation_spine.svg")


# ----------------------------------------------------------------------------- 06 dbt lineage
def dbt_lineage() -> None:
    if not MANIFEST.exists():
        print("  (skipped 06_dbt_lineage.svg -- run dbt first to produce dbt/target/manifest.json)")
        return
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    models, edges = {}, []
    for node in m["nodes"].values():
        if node["resource_type"] != "model":
            continue
        name = node["name"]
        models[name] = node.get("config", {}).get("materialized", "table")
        for dep in node["depends_on"]["nodes"]:
            upstream = m["sources"][dep]["name"] if dep.startswith("source.") else m["nodes"][dep]["name"]
            # A seed is an upstream input exactly as a source is. Leaving seeds out is what made
            # dim_date_saudi look parentless in the first draft of this picture.
            is_input = dep.startswith("source.") or dep.startswith("seed.")
            edges.append((upstream, name, is_input))
    tests = sum(1 for n in m["nodes"].values() if n["resource_type"] == "test")
    seeds = sum(1 for n in m["nodes"].values() if n["resource_type"] == "seed")

    s = Svg(1680, 870, "dbt lineage, read from the manifest",
            f"A dbt build here runs {len(models) + tests + seeds} nodes: {len(models)} models, "
            f"{tests} tests, {seeds} seeds. Generated from dbt/target/manifest.json, so it cannot "
            "describe a graph dbt does not have.")
    srcs = sorted({a for a, _b, is_src in edges if is_src})
    order = ["dim_date_saudi", "dim_party_golden", "fact_merchant_dispute_monitor",
             "fact_payment_method_daily", "fact_zatca_clearance_ledger",
             "fact_merchant_settlement_recon", "mart_ndmo_scorecard"]
    mods = [n for n in order if n in models] + [n for n in sorted(models) if n not in order]

    sx, sw = 40, 330
    mx, mw = 640, 420
    sy0 = 150
    sgap = min(60, (700 - sy0) // max(1, len(srcs) - 1)) if len(srcs) > 1 else 60
    spos, mpos = {}, {}
    s.text(sx, 128, "INPUTS  (Silver lakehouse, meta, seeds)", size=11.5, weight=700, fill=CYAN, mono=True)
    for i, n in enumerate(srcs):
        y = sy0 + i * sgap
        spos[n] = y + 20
        s.node(sx, y, sw, 40, n, "", accent=CYAN, size=11)
    s.text(mx, 128, "GOLD MODELS  (WH_MIZAN.gld)", size=11.5, weight=700, fill=EMERALD, mono=True)
    mgap = 66
    for i, n in enumerate(mods):
        y = sy0 + i * mgap
        mpos[n] = y + 24
        mat = models[n]
        s.node(mx, y, mw, 48, n, f"materialized: {mat}", accent=GOLD if "incremental" in mat else EMERALD,
               size=11.5)

    for a, b, _is_src in edges:
        y1 = spos.get(a) or mpos.get(a)
        y2 = mpos.get(b)
        if y1 is None or y2 is None:
            continue
        x1 = sx + sw if a in spos else mx + mw
        if a in mpos:  # model -> model: route around the right
            s.path(f"M {mx + mw} {y1} C {mx + mw + 70} {y1}, {mx + mw + 70} {y2}, {mx + mw + 6} {y2}",
                   stroke=GOLD, head="ag", sw=1.2)
            continue
        s.path(f"M {x1 + 4} {y1} C {mx - 90} {y1}, {mx - 90} {y2}, {mx - 6} {y2}",
               stroke=CYAN, head="a", sw=1.1)

    s.panel(1140, 150, 500, 380, "WHAT THE GRAPH DOES NOT SHOW", accent=INK)
    for i, t in enumerate([
            f"{tests} tests hang off these nodes. The ones that",
            "matter are not schema tests:",
            "",
            "  unexplained_bank_variance = 0.00",
            "  unexplained_gl_variance   = 0.00",
            "  every settled line matches its payment",
            "  zero ICV gaps, zero PIH breaks",
            "  accounting_postings == 1 per invoice_uuid",
            "",
            "These are the circuit breaker. A failure stops",
            "the build, and the candidate run is never",
            "published -- a wrong number is worse than a",
            "late one.",
            "",
            "fact_merchant_settlement_recon is incremental",
            "(delete+insert, on_schema_change=fail). It was",
            "executed on WH_MIZAN, not merely compiled."]):
        c = EMERALD if t.strip().startswith(("unexplained", "every", "zero", "accounting")) else MUTED
        s.text(1156, 212 + i * 19, t, size=10.5, fill=c, mono=True)

    s.panel(1140, 552, 500, 250, "THE INCREMENTAL CUT-OFF", accent=GOLD)
    for i, t in enumerate([
            "Watermark is arrival time, not business time:",
            "",
            "  WHERE source_ingested_at >= (",
            "    SELECT COALESCE(MAX(last_source_arrival_at),",
            "                    '1900-01-01') FROM {{ this }})",
            "",
            ">= and not >, because two rows can share a",
            "timestamp to the microsecond. Re-reading one",
            "row is free; missing one is a silent hole.",
            "",
            "A late bank file for an old trading day is",
            "picked up, because it ARRIVED today."]):
        s.text(1156, 596 + i * 17, t, size=10.5,
               fill=GOLD if t.strip().startswith(">=") else MUTED, mono=True)

    s.foot(STAMP + " | nodes and edges read from dbt/target/manifest.json")
    s.save("06_dbt_lineage.svg")


def rasterise() -> None:
    """Also emit PNG. SVG is right for the README; a Fabric notebook displays a PNG, and so does a
    video editor. Skipped silently if Playwright is not installed -- the SVGs are the deliverable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (no PNG: pip install playwright)")
        return
    png = OUT / "png"
    png.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for svg in sorted(OUT.glob("*.svg")):
            pg = b.new_page(viewport={"width": 1700, "height": 1060}, device_scale_factor=1.5)
            pg.set_content(f'<body style="margin:0;background:{NIGHT}">' + svg.read_text(encoding="utf-8"))
            pg.wait_for_timeout(450)
            pg.locator("svg").screenshot(path=str(png / (svg.stem + ".png")))
            pg.close()
            print(f"  docs/diagrams/png/{svg.stem}.png")
        b.close()


def main() -> None:
    print("building docs/diagrams/")
    architecture()
    dataflow_one_sale()
    schema_map()
    zatca_state_machine()
    reconciliation_spine()
    dbt_lineage()
    rasterise()


if __name__ == "__main__":
    main()
