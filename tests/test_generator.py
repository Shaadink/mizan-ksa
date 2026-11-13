"""Phase 1: deterministic generator \u2014 volumes, key contract (spec 7.1), money identities, planted defects."""

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from conftest import read_csv, read_jsonl
from mizan.common.saudi_ids import checksum_ok
from mizan.generator import GenConfig, generate
from mizan.generator.build import allocate, mojibake

KSA = timezone(timedelta(hours=3))
AMOUNT_RE = re.compile(r"^[0-9]+\.[0-9]{2}$")
ARABIC_INDIC = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")


def ksa_date(utc_iso: str) -> date:
    return datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(KSA).date()


@pytest.fixture(scope="session")
def data(gen_dir):
    settle = []
    for p in sorted((gen_dir / "settlement").glob("*.csv")):
        if "_RESEND" not in p.name:
            settle += read_csv(p)
    return {
        "orders": read_csv(gen_dir / "orders/commerce_events.csv"),
        "reqs": read_jsonl(gen_dir / "zatca/invoice_requests.jsonl"),
        "pay": read_csv(gen_dir / "payments/payment_events.csv"),
        "settle": settle,
        "gl": read_csv(gen_dir / "erp/erp_gl_acdoca.csv"),
        "pos": read_csv(gen_dir / "crm/crm_pos_cp1256.csv", encoding="cp1256"),
        "eco": read_csv(gen_dir / "crm/crm_ecom_utf8.csv"),
        "plan": json.loads((gen_dir / "zatca/fatoora_fault_plan.json").read_text(encoding="utf-8")),
    }


# ---------------------------------------------------------------- determinism + volumes

def test_byte_identical_rerun(gen_dir, tmp_path):
    second = generate(tmp_path, GenConfig())
    first = json.loads((gen_dir / "_control.json").read_text(encoding="utf-8"))
    assert first == second
    assert (gen_dir / "_control.json").read_bytes() == (tmp_path / "_control.json").read_bytes()


def test_different_seed_differs(tmp_path):
    a = generate(tmp_path / "a", GenConfig(seed=1))
    b = generate(tmp_path / "b", GenConfig(seed=2))
    assert a["files"]["payments/payment_events.csv"]["sha256"] != b["files"]["payments/payment_events.csv"]["sha256"]


def test_spec_volumes(manifest):
    c = manifest["counts"]
    assert c["commerce_events"] == 25_000
    assert c["invoice_requests"] == 25_000
    assert c["payment_events"] == 18_000
    assert c["settlement_lines"] == 17_000
    assert c["in_transit_events"] == 1_000
    assert c["crm_and_spl_records"] == 5_000
    assert 9_000 <= c["gl_lines"] <= 11_000
    assert 95_000 <= c["total_rows"] <= 105_000


def test_control_manifest_hashes_match_files(gen_dir):
    import hashlib
    control = json.loads((gen_dir / "_control.json").read_text(encoding="utf-8"))
    for rel, meta in control["files"].items():
        assert hashlib.sha256((gen_dir / rel).read_bytes()).hexdigest() == meta["sha256"], rel


def test_allocate_is_exact():
    assert sum(allocate(16_200, [1.0, 1.35, 0.9])) == 16_200
    assert allocate(10, [1, 1, 1, 1]) == [3, 3, 2, 2]


# ---------------------------------------------------------------- key contract (spec 7.1)

def test_payment_keys_resolve(data):
    orders = {o["order_id"] for o in data["orders"] if o["event_type"] == "ORDER_PLACED"}
    inv = {r["invoice_uuid"]: r for r in data["reqs"]}
    for p in data["pay"]:
        assert p["order_id"] in orders
        assert inv[p["invoice_uuid"]]["document_type"] == "INVOICE"
        assert inv[p["invoice_uuid"]]["order_id"] == p["order_id"]
        if p["event_type"] == "REFUND":
            cn = inv[p["credit_note_uuid"]]
            assert cn["document_type"] == "CREDIT_NOTE" and cn["billing_reference_uuid"] == p["invoice_uuid"]
            assert cn["total_incl_vat_sar"] == p["amount_sar"]
        else:
            assert p["credit_note_uuid"] == ""


def test_unique_ids(data):
    for rows, k in ((data["orders"], "event_id"), (data["pay"], "payment_event_id"),
                    (data["reqs"], "request_id"), (data["reqs"], "invoice_uuid")):
        vals = [r[k] for r in rows]
        assert len(vals) == len(set(vals)), k


def test_one_settlement_line_per_payment_event(data):
    ids = [s["payment_event_id"] for s in data["settle"]]
    assert len(ids) == len(set(ids))
    pay_ids = {p["payment_event_id"] for p in data["pay"]}
    assert set(ids) <= pay_ids


def test_in_transit_is_last_business_day(data, manifest):
    last = date.fromisoformat(manifest["period_ksa"][1])
    settled = {s["payment_event_id"] for s in data["settle"]}
    missing = [p for p in data["pay"] if p["payment_event_id"] not in settled]
    assert len(missing) == 1_000
    assert all(ksa_date(p["event_ts_utc"]) == last for p in missing)


def test_settlement_date_is_ksa_business_date(data):
    by_id = {p["payment_event_id"]: p for p in data["pay"]}
    for s in data["settle"]:
        assert s["settlement_for_date"] == ksa_date(by_id[s["payment_event_id"]]["event_ts_utc"]).isoformat()
        assert s["payout_date"] == (date.fromisoformat(s["settlement_for_date"]) + timedelta(days=1)).isoformat()


def test_midnight_utc_vs_ksa_cases_exist(data):
    crossing = [p for p in data["pay"] if p["event_ts_utc"][:10] != ksa_date(p["event_ts_utc"]).isoformat()]
    assert len(crossing) > 100  # a UTC-date bug would misassign these business dates


def test_order_invoice_payment_amounts_tie(data):
    totals = {r["order_id"]: r["total_incl_vat_sar"] for r in data["reqs"] if r["document_type"] == "INVOICE"}
    planted = data["plan"]["tape"]["positions"]["103"]
    planted_order = next(r["order_id"] for r in data["reqs"] if r["request_id"] == planted)
    for p in data["pay"]:
        if p["event_type"] == "CAPTURE" and p["order_id"] != planted_order:
            assert totals[p["order_id"]] == p["amount_sar"]


# ---------------------------------------------------------------- money rules

def test_amounts_positive_two_decimals(data):
    for p in data["pay"]:
        assert AMOUNT_RE.fullmatch(p["amount_sar"]) and Decimal(p["amount_sar"]) > 0
    for s in data["settle"]:
        for k in ("gross_amount", "mdr_fee", "vat_on_fee", "net_amount"):
            assert AMOUNT_RE.fullmatch(s[k]), (k, s[k])
    for g in data["gl"]:
        assert AMOUNT_RE.fullmatch(g["HSL"]) and Decimal(g["HSL"]) > 0
        assert g["DRCRK"] in ("S", "H")


def test_enums_uppercase(data):
    assert {p["event_type"] for p in data["pay"]} == {"CAPTURE", "REFUND", "CHARGEBACK"}
    assert {r["invoice_flow"] for r in data["reqs"]} == {"CLEARANCE", "REPORTING"}
    assert {r["document_type"] for r in data["reqs"]} == {"INVOICE", "CREDIT_NOTE"}
    assert {o["event_type"] for o in data["orders"]} == {"ORDER_PLACED", "RETURN_REQUESTED"}
    assert {s["dr_cr"] for s in data["settle"]} == {"CR", "DR"}


def test_five_egs_units(data):
    assert sorted({r["egs_id"] for r in data["reqs"]}) == [f"EGS-0{i}" for i in range(1, 6)]
    assert {r["invoice_flow"] for r in data["reqs"] if r["egs_id"] == "EGS-05"} == {"REPORTING"}


def test_gl_journals_balance(data):
    bal = defaultdict(Decimal)
    for g in data["gl"]:
        bal[g["BELNR"]] += Decimal(g["HSL"]) * (1 if g["DRCRK"] == "S" else -1)
    assert all(v == 0 for v in bal.values())


def _signed(p):
    return Decimal(p["amount_sar"]) * (1 if p["event_type"] == "CAPTURE" else -1)


def test_bank_leg_closes_to_zero(data):
    """Expected net (captures - refunds - chargebacks - bank fees) == signed bank net per MID x day."""
    by_id = {p["payment_event_id"]: p for p in data["pay"]}
    exp, bank = defaultdict(Decimal), defaultdict(Decimal)
    for s in data["settle"]:
        k = (s["merchant_id"], s["settlement_for_date"])
        exp[k] += _signed(by_id[s["payment_event_id"]]) - Decimal(s["mdr_fee"]) - Decimal(s["vat_on_fee"])
        bank[k] += Decimal(s["net_amount"]) * (1 if s["dr_cr"] == "CR" else -1)
    assert exp == bank


def test_gl_leg_closes_to_zero(data):
    """Net sales (captures - refunds - chargebacks) == GL card clearing per MID x posting day."""
    net, gl = defaultdict(Decimal), defaultdict(Decimal)
    for p in data["pay"]:
        net[(p["merchant_id"], ksa_date(p["event_ts_utc"]).strftime("%Y%m%d"))] += _signed(p)
    for g in data["gl"]:
        if g["RACCT"] == "113100":
            gl[(g["ZZ_MERCHANT_ID"], g["BUDAT"])] += Decimal(g["HSL"]) * (1 if g["DRCRK"] == "S" else -1)
    assert {k: v for k, v in net.items() if v} == {k: v for k, v in gl.items() if v}


def test_partial_refunds(data):
    cap = {p["order_id"]: Decimal(p["amount_sar"]) for p in data["pay"] if p["event_type"] == "CAPTURE"}
    refunds = [p for p in data["pay"] if p["event_type"] == "REFUND"]
    assert sum(Decimal(p["amount_sar"]) < cap[p["order_id"]] for p in refunds) > len(refunds) * 0.5
    assert all(Decimal(p["amount_sar"]) <= cap[p["order_id"]] for p in refunds)


# ---------------------------------------------------------------- planted defects

def test_twelve_defects_declared(manifest):
    ids = [d["id"] for d in manifest["defects"]]
    assert ids == [f"D{i:02d}" for i in range(1, 13)]
    names = {d["name"] for d in manifest["defects"]}
    # the six the spec names explicitly (Day-1 row)
    for n in ("ZATCA_TRANSPORT_TIMEOUT", "ZATCA_ICV_GAP_TAMPER", "CP1256_MOJIBAKE", "BROTHER_HARD_NEGATIVE",
              "ORPHAN_SETTLEMENT_LINE", "MEGA_MID_SKEW_AND_WALK_IN"):
        assert n in names


def test_mega_mid_skew_65pct(data):
    share = Counter(p["merchant_id"] for p in data["pay"])["MID900001"] / len(data["pay"])
    assert 0.63 <= share <= 0.67


def test_walk_in_null_keys(data):
    pos = [o for o in data["orders"] if o["event_type"] == "ORDER_PLACED" and o["channel"] == "POS"]
    assert 0.2 < sum(o["customer_ref"] == "" for o in pos) / len(pos) < 0.4


def test_orphan_overlay(gen_dir, data):
    orphan = read_csv(gen_dir / "demo/settlement_demo_orphan.csv")
    assert len(orphan) == 1
    assert orphan[0]["payment_event_id"] not in {p["payment_event_id"] for p in data["pay"]}


def test_float_bug_overlay_is_one_halala(gen_dir, data):
    fb = read_csv(gen_dir / "demo/erp_gl_demo_float_bug.csv")[0]
    base = next(g for g in data["gl"] if g["BELNR"] == fb["BELNR"] and g["DOCLN"] == fb["DOCLN"])
    assert base["RACCT"] == "113100"
    assert Decimal(base["HSL"]) - Decimal(fb["HSL"]) == Decimal("0.01")


def test_duplicate_settlement_file_is_byte_identical(gen_dir, manifest):
    d07 = next(d for d in manifest["defects"] if d["id"] == "D07")["location"]
    assert (gen_dir / d07["file"]).read_bytes() == (gen_dir / d07["duplicate_of"]).read_bytes()


def test_zatca_fault_plan_tape(data):
    plan = data["plan"]
    egs05 = [r for r in data["reqs"] if r["egs_id"] == "EGS-05"]
    for pos, rid in plan["tape"]["positions"].items():
        assert egs05[int(pos) - 1]["request_id"] == rid
    p102, p103 = plan["tape"]["positions"]["102"], plan["tape"]["positions"]["103"]
    assert plan["responses"][p102] == ["TRANSPORT_TIMEOUT", "WORKER_CRASH_IN_SUBMITTING", "HTTP_200"]
    assert plan["responses"][p103] == ["HTTP_400"]
    r103 = next(r for r in data["reqs"] if r["request_id"] == p103)
    line_vat = sum(Decimal(ln["line_vat_sar"]) for ln in r103["lines"])
    assert Decimal(r103["vat_total_sar"]) - line_vat == Decimal("0.01")
    egs03 = [r for r in data["reqs"] if r["egs_id"] == "EGS-03"]
    assert plan["tamper"][0]["request_id"] == egs03[499]["request_id"]


def test_pos_crm_is_real_windows_1256(gen_dir):
    raw = (gen_dir / "crm/crm_pos_cp1256.csv").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    golden_ar = "\u0645\u062D\u0645\u062F \u0628\u0644\u0627\u0644 \u0627\u0644\u0639\u062A\u064A\u0628\u064A"
    assert golden_ar.encode("cp1256") in raw


def test_mojibake_rows_reverse_to_arabic(data, manifest):
    d08 = next(d for d in manifest["defects"] if d["id"] == "D08")["location"]["mojibake_ids"]
    eco = {r["source_customer_id"]: r for r in data["eco"]}
    assert len(d08) == 41
    for cid in d08:
        s = eco[cid]["full_name_ar"]
        assert not any("\u0600" <= c <= "\u06FF" for c in s)
        raw = bytes(ord(c) if ord(c) < 256 else c.encode("cp1252")[0] for c in s)
        assert any("\u0600" <= c <= "\u06FF" for c in raw.decode("cp1256"))


def test_mojibake_helper_known_value():
    assert mojibake("\u0639") == "\u00DA"  # cp1256 0xDA (ain) read as cp1252


def test_unrecoverable_qmarks(data, manifest):
    ids = next(d for d in manifest["defects"] if d["id"] == "D09")["location"]["ids"]
    pos = {r["source_customer_id"]: r for r in data["pos"]}
    assert len(ids) == 15
    assert all(set(pos[i]["full_name_ar"]) == {"?"} for i in ids)


def test_brothers_hard_negative(data, manifest):
    loc = next(d for d in manifest["defects"] if d["id"] == "D10")["location"]
    rows = {r["source_customer_id"]: r for r in data["pos"] + data["eco"]}
    a, b = (rows[i] for i in loc["brothers"])
    third = rows[loc["id_less_third"]]
    assert a["national_id"] != b["national_id"]
    assert checksum_ok(a["national_id"]) and checksum_ok(b["national_id"])
    assert a["landline"] == b["landline"] == third["landline"] != ""
    assert third["national_id"] == ""


def test_five_spellings_share_one_valid_id(data, manifest):
    ids = next(d for d in manifest["defects"] if d["id"] == "D11")["location"]["ids"]
    rows = {r["source_customer_id"]: r for r in data["pos"] + data["eco"]}
    surface = [(rows[i]["full_name_ar"], rows[i]["full_name_en"]) for i in ids]
    assert len(set(surface)) == 5
    folded = {rows[i]["national_id"].translate(ARABIC_INDIC) for i in ids}
    assert len(folded) == 1 and checksum_ok(folded.pop())
    assert any("\uFEFB" in s[0] for s in surface)
    assert any(any("\u0660" <= c <= "\u0669" for c in rows[i]["national_id"]) for i in ids)


def test_all_person_ids_valid_after_folding(data):
    for r in data["pos"] + data["eco"]:
        if r["national_id"]:
            assert checksum_ok(r["national_id"].translate(ARABIC_INDIC)), r["source_customer_id"]
