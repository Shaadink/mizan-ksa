"""Phase 5, Module 4 (pure Python): Typed Identifier Registry, hard-negative brother test, steward routing,
reversible merge ledger, idempotent re-runs. No Spark needed."""

import hashlib
import json

import pytest

from mizan.common.saudi_ids import to_arabic_indic
from mizan.mdm import engine as E
from mizan.mdm.arabic_norm_and_privacy import build_arabic_search_key, validate_saudi_10digit_id

# synthetic, checksum-valid IDs (minted by mizan.common.saudi_ids rules)
GOLDEN_AR = "\u0645\u062D\u0645\u062F \u0628\u0644\u0627\u0644 \u0627\u0644\u0639\u062A\u064A\u0628\u064A"
TASHKEEL_LIG = ("\u0645\u064F\u062D\u064E\u0645\u0651\u064E\u062F \u0628\uFEFB\u0644 "
                "\u0627\u0644\u0639\u064F\u062A\u064E\u064A\u0652\u0628\u0650\u064A")
QAHTANI = "\u0639\u0628\u062F\u0627\u0644\u0644\u0647 \u0627\u0644\u0642\u062D\u0637\u0627\u0646\u064A"
ALI_AR = "\u0639\u0644\u064A " + QAHTANI
OMAR_AR = "\u0639\u0645\u0631 " + QAHTANI
THIRD_AR = "\u0639. " + QAHTANI


def mint_id(prefix: str, body: str) -> str:
    """Complete a 9-digit stem with the Modulo-10 check digit."""
    stem = prefix + body
    for d in "0123456789":
        if validate_saudi_10digit_id(stem + d):
            return stem + d
    raise AssertionError


G_ID, A_ID, B_ID = mint_id("1", "03456789"), mint_id("1", "11111111"), mint_id("1", "22222222")
LANDLINE = "0114567890"


def hm(purpose: str, value: str) -> str:
    return hashlib.sha256(f"test-key|{purpose}|{value}".encode()).hexdigest()


def rec(token, **kw):
    base = {"source": "crm_pos", "party_type": "PERSON", "created_date": "2024-01-01"}
    base.update(kw)
    for col in ("name_ar", "name_en"):
        if base.get(col):
            base[f"{col}_enc"] = f"ct:{token}:{col}"
    return E.PartyRecord(token=token, **base)


def scenario():
    return [
        rec("t1", name_ar=GOLDEN_AR, national_id=G_ID, mobile="0537660841", name_encoding_status="DECODED_CP1256"),
        rec("t2", name_en="Mohd Otaibi", national_id=G_ID, mobile="0537660841"),
        rec("t3", source="crm_ecom", name_ar=GOLDEN_AR, national_id=G_ID, name_encoding_status="REPAIRED_MOJIBAKE"),
        rec("t4", source="crm_ecom", name_ar=TASHKEEL_LIG, national_id=to_arabic_indic(G_ID)),
        rec("t5", source="crm_ecom", name_en="Mohammed Bilal Al Otaibi", national_id=G_ID),
        rec("bA", name_ar=ALI_AR, name_en="Ali Abdullah Al Qahtani", national_id=A_ID, landline=LANDLINE),
        rec("bB", source="crm_ecom", name_ar=OMAR_AR, name_en="Omar Abdullah Al Qahtani", national_id=B_ID,
            landline=LANDLINE),
        rec("x3", name_ar=THIRD_AR, name_en="A. Abdullah Al Qahtani", landline=LANDLINE),
        rec("solo", name_en="Sara Al Harbi", mobile="0551112222"),
        rec("solo2", source="crm_ecom", name_en="Sara Al Harbi", mobile="0551112222",
            national_id=mint_id("2", "33333333")),
        rec("org", party_type="ORGANIZATION", name_en="Najd Trading Co", vat_number="300000000000003",
            unified_700="7001234567"),
    ]


def test_search_key_folds_the_three_arabic_spellings():
    assert build_arabic_search_key(TASHKEEL_LIG) == build_arabic_search_key(GOLDEN_AR)
    assert build_arabic_search_key("Mohammed  Bilal-Al Otaibi") == "mohammed bilal al otaibi"


def test_typed_identifier_registry_rules():
    ids = E.type_identifiers(rec("z", national_id=to_arabic_indic(G_ID)))
    assert [(i.id_type, i.canonical, i.status, i.is_anchor) for i in ids] == [("NATIONAL_ID", G_ID, "VALID_CHECKSUM",
                                                                               True)]
    bad = G_ID[:-1] + str((int(G_ID[-1]) + 1) % 10)
    assert E.type_identifiers(rec("z", national_id=bad))[0].status == "INVALID_CHECKSUM"
    assert not E.type_identifiers(rec("z", national_id=bad))[0].is_anchor
    org = E.type_identifiers(rec("o", party_type="ORGANIZATION", vat_number="300000000000003",
                                 unified_700="7001234567"))
    assert [(i.id_type, i.status) for i in org] == [("VAT", "VALID_FORMAT"), ("UNIFIED_700", "FORMAT_ONLY")]
    assert E.type_identifiers(rec("o", party_type="ORGANIZATION", vat_number="310000000000001"))[0].status \
        == "INVALID_FORMAT"
    assert E.canonical_phone("+966 11 456 7890") == "0114567890"


def test_five_spellings_merge_into_one_golden_id():
    res = E.resolve(scenario(), hm)
    assert len({res.membership[t] for t in ("t1", "t2", "t3", "t4", "t5")}) == 1
    g = next(x for x in res.goldens if x["golden_id"] == res.membership["t1"])
    assert g["member_count"] == 5 and g["anchor_id_type"] == "NATIONAL_ID"
    assert g["name_ar_source_token"] == "t1"            # clean CP1256 source beats repaired mojibake
    assert g["name_en_source_token"] == "t5"            # full English name beats 'Mohd Otaibi'


def test_hard_negative_brothers_never_merge_and_third_goes_to_steward():
    res = E.resolve(scenario(), hm)
    assert res.membership["bA"] != res.membership["bB"]
    assert "x3" not in res.membership                     # never auto-merged, no golden profile either
    (c,) = [c for c in res.conflicts if c["subject_token_id"] == "x3"]
    assert c["conflict_type"] == "AMBIGUOUS_IDLESS_MATCH" and c["status"] == "OPEN"
    assert set(json.loads(c["candidate_golden_ids"])) == {res.membership["bA"], res.membership["bB"]}


def test_idless_record_attaches_only_to_a_unique_candidate():
    res = E.resolve(scenario(), hm)
    assert res.membership["solo"] == res.membership["solo2"]     # same name + same mobile, one candidate
    ev = {e["subject_token_id"]: e for e in res.ledger_new}
    assert ev["solo"]["match_rule"] == "NAME_PHONE_UNIQUE" and ev["solo2"]["match_rule"] == "ANCHOR_IQAMA"
    assert res.membership["org"] != res.membership["t1"]
    assert {r["id_type"] for r in res.registry} == {"NATIONAL_ID", "IQAMA", "VAT", "UNIFIED_700"}


def test_rerun_is_idempotent_and_golden_ids_are_deterministic():
    first = E.resolve(scenario(), hm)
    again = E.resolve(list(reversed(scenario())), hm, prior_ledger=first.ledger_new, prior_conflicts=first.conflicts)
    assert again.ledger_new == [] and again.membership == first.membership
    assert [c["status"] for c in again.conflicts] == ["OPEN"]


def test_steward_assignment_is_respected_and_conflict_resolved():
    first = E.resolve(scenario(), hm)
    gid_a = first.membership["bA"]
    ev = E.steward_event(first.ledger_new, "x3", gid_a, "MERGE", "steward.najd", "phone call confirmed Ali", "t")
    ledger = first.ledger_new + [ev]
    res = E.resolve(scenario(), hm, prior_ledger=ledger, prior_conflicts=first.conflicts)
    assert res.membership["x3"] == gid_a and res.ledger_new == []
    assert [c["status"] for c in res.conflicts if c["subject_token_id"] == "x3"] == ["RESOLVED"]


def test_every_merge_is_reversible_through_the_ledger():
    first = E.resolve(scenario(), hm)
    gid = first.membership["t2"]
    ev = E.steward_event(first.ledger_new, "t2", gid, "UNMERGE", "steward.najd", "wrong person", "t")
    ledger = first.ledger_new + [ev]
    members, pinned = E.membership_from_ledger(ledger)
    assert "t2" not in members and "t2" in pinned
    res = E.resolve(scenario(), hm, prior_ledger=ledger)
    assert res.membership["t2"] != gid                      # stands alone; the anchor does NOT re-merge it
    assert [e["match_rule"] for e in res.ledger_new] == ["NEW_GOLDEN"]
    assert sum(1 for t, g in res.membership.items() if g == gid) == 4


def test_unknown_party_type_raises():
    with pytest.raises(ValueError):
        E.resolve([rec("q", party_type="person")], hm)
    with pytest.raises(ValueError):
        E.steward_event([], "q", "GP-X", "MERGE", E.SYSTEM, "x", "t")
