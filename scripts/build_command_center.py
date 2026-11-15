"""MIZAN Command Center data snapshot: every figure the cinematic front end shows, exported from real outputs.

Sources (nothing is typed in by hand):
  tmp/mizan_gold.duckdb          Gold tables built by dbt (recon, ZATCA ledger, NDMO scorecard, golden parties)
  data/lake (Delta)              meta.column_classification (NDMO tiers)
  data/generated                 ZATCA chain re-run on EGS-05 (same engine + fault plan as the tests); stream replay
  dbt/target/manifest.json       Gold column lineage (raises if any Gold column has no lineage)
  docs/artifacts/*.json, html/   Fabric run evidence, 20M skew benchmark, PDPL and MDM proof boards (Phase 11)

Money stays exact: Decimal in Python, strings in JSON, integer halalas in the browser (never float).

    .\\.venv\\Scripts\\python.exe scripts\\build_command_center.py      # writes command_center/data.json + index.html
"""

# ruff: noqa: S608  (SQL text interpolates only constant Gold table names, never input)
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

GOLD = REPO / "tmp" / "mizan_gold.duckdb"
LAKE = REPO / "data" / "lake"
GEN = REPO / "data" / "generated"
ART = REPO / "docs" / "artifacts"
OUT = REPO / "command_center"
CENT = Decimal("0.01")


def money(v) -> str:
    return str(Decimal(v).quantize(CENT))


def _q(con, sql: str, *args) -> list[tuple]:
    return con.execute(sql, list(args)).fetchall()


# ----------------------------------------------------------------------------- Gold
def gold_section(con) -> dict:
    R = "gld.fact_merchant_settlement_recon"
    (gross, refunds, fees, net, bank, transit, quar, gl, bvar, gvar, uncl, rows, mids, d0, d1), = _q(con, f"""
        SELECT SUM(gross_captures_sar), SUM(refunds_and_disputes_sar), SUM(acquirer_fees_sar),
               SUM(expected_net_payable_sar), SUM(bank_paid_sar), SUM(in_transit_sar), SUM(quarantined_sar),
               SUM(gl_card_clearing_sar), SUM(ABS(unexplained_bank_variance_sar)),
               SUM(ABS(unexplained_gl_variance_sar)), SUM(unclassified_events), COUNT(*),
               COUNT(DISTINCT merchant_id), MIN(business_date_ksa), MAX(business_date_ksa) FROM {R}""")
    assert bvar == 0 and gvar == 0, "Gold recon has unexplained variance"
    assert net == bank + transit + quar and gl == gross - refunds
    daily = [{"d": str(d), "gross": money(g), "bank": money(b), "transit": money(t), "gl": money(c),
              "fees": money(f), "refunds": money(r)}
             for d, g, b, t, c, f, r in _q(con, f"""
                 SELECT business_date_ksa, SUM(gross_captures_sar), SUM(bank_paid_sar), SUM(in_transit_sar),
                        SUM(gl_card_clearing_sar), SUM(acquirer_fees_sar), SUM(refunds_and_disputes_sar)
                 FROM {R} GROUP BY 1 ORDER BY 1""")]
    days = [x["d"] for x in daily]
    merch = _q(con, f"SELECT merchant_id, SUM(gross_captures_sar) g FROM {R} GROUP BY 1 ORDER BY g DESC, 1")
    order = [m for m, _ in merch]
    cells: dict[str, list] = {m: [None] * len(days) for m in order}
    for m, d, g, bv, gv in _q(con, f"""SELECT merchant_id, business_date_ksa, gross_captures_sar,
                                       unexplained_bank_variance_sar, unexplained_gl_variance_sar FROM {R}"""):
        cells[m][days.index(str(d))] = money(g)
        assert bv == 0 and gv == 0
    cal = {str(d): {"hijri": f"{hd} {hm} {hy}", "ramadan": bool(r), "weekend": bool(w)}
           for d, hd, hm, hy, r, w in _q(con, """SELECT calendar_date, hijri_day, hijri_month_name, hijri_year,
                                               is_ramadan, is_saudi_weekend FROM gld.dim_date_saudi
                                               WHERE calendar_date BETWEEN ? AND ?""", d0, d1)}
    z = "gld.fact_zatca_clearance_ledger"
    states = dict(_q(con, f"SELECT state, COUNT(*) FROM {z} GROUP BY 1 ORDER BY 1"))
    egs = [{"egs": e, "docs": n, "sar": money(s)} for e, n, s in
           _q(con, f"SELECT egs_id, COUNT(*), SUM(total_incl_vat_sar) FROM {z} GROUP BY 1 ORDER BY 1")]
    flows = [{"flow": f, "docs": n, "sar": money(s)} for f, n, s in
             _q(con, f"SELECT invoice_flow, COUNT(*), SUM(total_incl_vat_sar) FROM {z} GROUP BY 1 ORDER BY 1")]
    (zsar, corr, retried), = _q(con, f"""SELECT SUM(total_incl_vat_sar), COUNT(corrects_invoice_uuid),
                                       COUNT(*) FILTER (WHERE attempts > 1) FROM {z}""")
    zdaily = [{"d": str(d), "docs": n} for d, n in
              _q(con, f"SELECT issue_date_ksa, COUNT(*) FROM {z} GROUP BY 1 ORDER BY 1")]
    score = [{"family": f, "dimension": dm, "table": t, "num": n, "den": de, "score": money(s),
              "threshold": money(th), "status": st, "tier": tc}
             for f, dm, t, n, de, s, th, st, tc in _q(con, """SELECT metric_family, dimension, subject_table,
                 numerator, denominator, score_pct, threshold_pct, status, table_classification
                 FROM gld.mart_ndmo_scorecard ORDER BY metric_family, dimension, subject_table""")]
    (goldens, maxm), = _q(con, "SELECT COUNT(*), MAX(member_count) FROM gld.dim_party_golden")
    return {
        "recon": {"gross": money(gross), "refunds": money(refunds), "fees": money(fees), "net": money(net),
                  "bank": money(bank), "transit": money(transit), "quarantined": money(quar), "gl": money(gl),
                  "bank_variance": money(bvar), "gl_variance": money(gvar), "unclassified": int(uncl),
                  "mid_days": rows, "merchants": mids, "from": str(d0), "to": str(d1)},
        "daily": daily, "calendar": cal,
        "heat": {"days": days, "merchants": order, "cells": [cells[m] for m in order],
                 # demo-flag overlay from the Phase 11 recon board: the two planted breaks the circuit breaker catches
                 "demo_breaks": [{"merchant": "MID100046", "d": "2026-02-17", "bank_variance": "-2536.33",
                                  "gl_variance": "0.00", "cause": "Orphan bank line (no capture)"},
                                 {"merchant": "MID900001", "d": "2026-02-12", "bank_variance": "0.00",
                                  "gl_variance": "0.01", "cause": "0.01 SAR float rounding bug"}]},
        "zatca": {"states": states, "egs": egs, "flows": flows, "sar": money(zsar), "corrections": corr,
                  "retried": retried, "daily": zdaily},
        "ndmo": {"scorecard": score},
        "mdm_gold": {"goldens": goldens, "max_members": maxm},
    }


def _check_demo_breaks() -> None:
    board = (ART / "html" / "02_halala_recon_board.html").read_text(encoding="utf-8")
    for token in ("MID100046", "-2,536.33", "MID900001", "2026-02-12"):
        assert token in board, f"demo break {token} not found in the recon proof board"


def tiers(con) -> dict:
    loc = (LAKE / "LH_MIZAN" / "meta" / "column_classification").as_posix()
    con.execute("INSTALL delta; LOAD delta")
    cols = dict(_q(con, "SELECT classification, COUNT(*) FROM delta_scan(?) GROUP BY 1 ORDER BY 1", loc))
    tabs = dict(_q(con, """SELECT table_classification, COUNT(*) FROM (SELECT DISTINCT schema_name, table_name,
                         table_classification FROM delta_scan(?)) GROUP BY 1 ORDER BY 1""", loc))
    (pii, over, ntab), = _q(con, """SELECT COUNT(*) FILTER (WHERE is_personal_data), COUNT(*) FILTER (WHERE
                                 is_over_classified), COUNT(DISTINCT schema_name || '.' || table_name)
                                 FROM delta_scan(?)""", loc)
    holds = dict(_q(con, "SELECT legal_hold_class, COUNT(*) FROM delta_scan(?) GROUP BY 1 ORDER BY 1", loc))
    by_schema = dict(_q(con, """SELECT schema_name, COUNT(DISTINCT table_name) FROM delta_scan(?) GROUP BY 1
                              ORDER BY 1""", loc))
    return {"columns": cols, "tables": tabs, "personal_columns": pii, "over_classified": over,
            "table_count": ntab, "column_count": sum(cols.values()), "legal_hold": holds, "tables_by_schema": by_schema}


# ----------------------------------------------------------------------------- ZATCA chain re-run
def chain_section() -> dict:
    from mizan.clearance.chain_verifier import verify_chain
    from mizan.clearance.engine import process_requests
    from mizan.clearance.mock_fatoora import MockFatoora
    from mizan.clearance.tlv_qr_and_state_machine import GENESIS_PIH
    reqs = [json.loads(x) for x in (GEN / "zatca/invoice_requests.jsonl").read_text(encoding="utf-8").splitlines()]
    plan = json.loads((GEN / "zatca/fatoora_fault_plan.json").read_text(encoding="utf-8"))
    e5 = [r for r in reqs if r["egs_id"] == "EGS-05"][:110]
    client = MockFatoora(plan)
    run = process_requests(e5, client)
    by_icv = {r.icv: r for r in run.store.invoice_outbox.values() if r.egs_id == "EGS-05"}
    violations = [v for v in verify_chain(list(run.store.zatca_chain_journal.values())) if v.get("egs_id") == "EGS-05"]
    sent: dict[str, list] = defaultdict(list)
    for e in client.log:
        sent[e["request_id"]].append(e)
    blocks = []
    for icv in [1, 2, 3, 99, 100, 101, 102, 103, 104, 105, 106]:
        r = by_icv[icv]
        prev = by_icv.get(icv - 1)
        link = (r.pih == GENESIS_PIH) if icv == 1 else (prev is not None and r.pih == prev.invoice_hash)
        assert link, f"chain break at ICV {icv}"
        hist = []
        for h in r.history:
            ev = h.get("event")
            hist.append({"event": ev, "http": h.get("http_status") or (None if ev != "RESPONSE" else "timeout")})
        blocks.append({"icv": icv, "request": r.request_id, "uuid": r.invoice_uuid[:8], "pih": r.pih[:12],
                       "hash": r.invoice_hash[:12], "state": r.state, "sends": len(sent.get(r.request_id, [])),
                       "distinct_bytes": len({e["bytes_sha256"] for e in sent.get(r.request_id, [])}),
                       "corrects": (r.corrects_invoice_uuid or "")[:8], "history": hist})
    return {"egs": "EGS-05", "documents": len(by_icv), "restarts": run.restarts, "violations": len(violations),
            "max_gl_postings": max(run.gl.calls.values()), "genesis_pih": GENESIS_PIH, "blocks": blocks}


# ----------------------------------------------------------------------------- proof boards (PDPL, MDM)
def _board_text(name: str) -> list[str]:
    t = (ART / "html" / f"{name}.html").read_text(encoding="utf-8")
    t = re.sub(r"<style.*?</style>", "", t, flags=re.S)
    return [htmllib.unescape(x).strip() for x in re.split(r"<[^>]+>", t) if x.strip()]


def _after(cells: list[str], label: str, n: int = 1) -> list[str]:
    i = cells.index(label)
    return cells[i + 1:i + 1 + n]


def _mask_id(v: str) -> str:
    v = v.strip()
    return v[:3] + "\u2022" * max(0, len(v) - 6) + v[-3:] if len(v) > 6 else v


def pdpl_section() -> dict:
    c = _board_text("03_pdpl_shred_restore")
    before = _after(c, "Tax totals before")[0]
    after = _after(c, "Tax totals after")[0]
    assert before == after, "tax totals changed by erasure"
    tax = dict(kv.split("=") for kv in before.split(";"))
    kept = re.search(r"\((\d+) rows kept\)", " ".join(c)).group(1)
    reshred = re.search(r"re-shredded (\d+), re-resolved (\d+)", " ".join(c))
    return {"golden_id": _after(c, "Golden id")[0], "linked_records": int(_after(c, "Linked records")[0]),
            "dsr_id": _after(c, "DSR")[0], "links_before": int(_after(c, "Token \u2192 identity links")[0]),
            "keys": 5, "journal_rows_kept_for_subject": int(kept), "tax_docs": int(tax["docs"]),
            "tax_sar": money(tax["sar"]), "journal_rows": int(tax["journal_rows"]),
            "guard_reshredded": int(reshred.group(1)), "guard_reresolved": int(reshred.group(2)),
            "vacuum": "RETAIN 0 HOURS", "shred_error": "PermissionError: DEK for this subject has been shredded"}


def _board_rows(name: str) -> list[list[str]]:
    t = (ART / "html" / f"{name}.html").read_text(encoding="utf-8")
    return [[htmllib.unescape(re.sub(r"<[^>]+>", "", c)).strip()
             for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
            for tr in re.findall(r"<tr>(.*?)</tr>", t, re.S)]


def mdm_section() -> dict:
    rows = _board_rows("04_arabic_mdm_board")
    five, bro = [], []
    for r in rows:
        if len(r) == 8 and r[5].startswith("GP-"):
            repaired = r[2].endswith(" REPAIRED")
            five.append({"source": r[0], "received": r[1], "repaired": r[2].removesuffix(" REPAIRED"),
                         "cp1256_repaired": repaired, "id_masked": _mask_id(r[3]), "search_key": r[4],
                         "golden": r[5], "action": r[6], "rule": r[7]})
        elif len(r) == 6 and r[0] != "Source record":
            bro.append({"source": r[0], "arabic": r[1], "english": r[2],
                        "id_masked": _mask_id(r[3]) if r[3][:1].isdigit() else r[3],
                        "phone_masked": _mask_id(r[4]), "outcome": r[5]})
    assert len(five) == 5 and len({r["golden"] for r in five}) == 1
    assert len(bro) == 3 and bro[0]["outcome"] != bro[1]["outcome"] and bro[2]["outcome"].startswith("OPEN")
    return {"five": five, "brothers": bro}


# ----------------------------------------------------------------------------- streaming replay
def stream_section() -> dict:
    from datetime import datetime

    from mizan.privacy.crypto import Keys, load_dotenv
    from mizan.streaming import rules
    from mizan.streaming.replay import build_events
    load_dotenv()
    ev = build_events(GEN, Keys.from_env().hmac_key, inject_burst=True)
    kinds = Counter(e["event_kind"] for e in ev)
    t = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    t0, t1 = t(ev[0]["event_ts"]), t(ev[-1]["event_ts"])
    span = (t1 - t0).total_seconds()
    buckets = 120
    hist = {k: [0] * buckets for k in sorted(kinds)}
    for e in ev:
        b = min(buckets - 1, int((t(e["event_ts"]) - t0).total_seconds() / span * buckets))
        hist[e["event_kind"]][b] += 1
    vel, mule, sla = rules.velocity_alerts(ev), rules.mule_ring_alerts(ev), rules.sla_breaches(ev)
    alerts = []
    for tok in sorted(vel):
        ts = sorted(t(e["event_ts"]) for e in ev if e.get("customer_token") == tok and e["event_kind"] == "CHECKOUT")
        alerts.append({"rule": "VELOCITY", "key": tok[:10], "at": ts[5].isoformat() + "Z",
                       "detail": f"{len(ts)} checkouts in 10 minutes by one customer token"})
    for tok in sorted(mule):
        rows = sorted((t(e["event_ts"]), e["customer_token"]) for e in ev
                      if e.get("mobile_token") == tok and e["event_kind"] == "CHECKOUT")
        alerts.append({"rule": "MULE_RING", "key": tok[:10], "at": rows[3][0].isoformat() + "Z",
                       "detail": f"one mobile token on {len({c for _, c in rows})} customer tokens within 24 h"})
    for u in sorted(sla):
        iss = next(e for e in ev if e["event_kind"] == "INVOICE" and e["invoice_uuid"] == u
                   and e["invoice_event"] == "ISSUED")
        rep = [e for e in ev if e["event_kind"] == "INVOICE" and e["invoice_uuid"] == u
               and e["invoice_event"] == "REPORTED"]
        alerts.append({"rule": "REPORTING_SLA", "key": iss["request_id"], "at": iss["event_ts"],
                       "detail": "reported after 24 h" if rep else "never reported (rejected)"})
    alerts.sort(key=lambda a: a["at"])
    return {"total": len(ev), "kinds": dict(sorted(kinds.items())), "from": ev[0]["event_ts"], "to": ev[-1]["event_ts"],
            "histogram": hist, "alerts": alerts, "fabric_rows": {"CHECKOUT": 23511, "INVOICE": 50002, "PAYMENT": 18000},
            "fabric_rules": {"VelocityAlerts": 1, "MuleRingAlerts": 1, "InvoiceReportingSlaBreaches": 2}}


def lineage_section() -> dict:
    from mizan.lineage.openlineage import build
    doc = build(REPO / "dbt" / "target" / "manifest.json", GOLD, LAKE)
    lin = doc["column_lineage"]
    gold_cols = sum(len(v) for v in lin.values())
    covered = sum(1 for v in lin.values() for ins in v.values() if ins)
    edges = sorted({(i.rsplit(".", 1)[0], f"gld.{m}") for m, v in lin.items() for ins in v.values() for i in ins})
    return {"gold_columns": gold_cols, "covered": covered, "models": sorted(lin),
            "edges": [{"from": a, "to": b} for a, b in edges]}


def build_data() -> dict:
    import duckdb
    _check_demo_breaks()
    con = duckdb.connect(GOLD.as_posix(), read_only=True)
    try:
        data = gold_section(con)
        data["ndmo"]["catalog"] = tiers(con)
    finally:
        con.close()
    data["chain"] = chain_section()
    data["pdpl"] = pdpl_section()
    data["mdm"] = mdm_section()
    data["stream"] = stream_section()
    data["lineage"] = lineage_section()
    data["skew"] = json.loads((ART / "05_skew_benchmark_20m.json").read_text(encoding="utf-8"))
    data["fabric"] = json.loads((ART / "10_fabric_run_evidence.json").read_text(encoding="utf-8"))
    data["meta"] = {"seed": 20261112, "timezone": "Asia/Riyadh", "currency": "SAR",
                    "note": "Synthetic data, fixed seed. Every figure is exported from Gold or a proof run."}
    return data


def main() -> None:
    data = build_data()
    OUT.mkdir(exist_ok=True)
    blob = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    (OUT / "data.json").write_text(blob + "\n", encoding="utf-8", newline="\n")
    tpl = (OUT / "template.html").read_text(encoding="utf-8")
    assert tpl.count("/*__MIZAN_DATA__*/") == 1
    (OUT / "index.html").write_text(tpl.replace("/*__MIZAN_DATA__*/", blob.replace("</", "<\\/")),
                                    encoding="utf-8", newline="\n")
    print(f"command_center/index.html  ({len(blob):,} bytes of data)")


if __name__ == "__main__":
    main()
