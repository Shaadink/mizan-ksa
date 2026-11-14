"""Phase 5, Module 4 in the lakehouse: golden profiles from brz.crm_party_raw (I-09, I-10).

The answer key is rebuilt independently from the source CSVs: a record with a checksum-valid ID belongs to that
ID; an ID-less record belongs to the ID-bearing record with the same mobile. The engine never sees this oracle.
"""

import json
import shutil
from collections import defaultdict

import pytest

pytest.importorskip("pyspark")
pytestmark = pytest.mark.spark

from conftest import read_csv  # noqa: E402
from mizan.mdm.arabic_norm_and_privacy import validate_saudi_10digit_id  # noqa: E402
from mizan.mdm.engine import canonical_phone  # noqa: E402
from mizan.privacy import crypto  # noqa: E402

MDM_TABLES = (("slv", "golden_party_scd2"), ("slv", "identifier_registry"), ("slv", "entity_merge_ledger"),
              ("slv", "address_observations"), ("quarantine", "mdm_match_conflicts"))


def crm_rows(gen_dir):
    return (read_csv(gen_dir / "crm/crm_pos_cp1256.csv", "cp1256")
            + read_csv(gen_dir / "crm/crm_ecom_utf8.csv"))


def ids_of(manifest, defect):
    return next(d for d in manifest["defects"] if d["id"] == defect)["location"]


def current_members(lake, test_keys, gen_dir):
    """source_customer_id -> golden_id, from the current SCD2 rows."""
    tok = {crypto.token_for(test_keys.hmac_key, r["source_customer_id"]): r["source_customer_id"]
           for r in crm_rows(gen_dir)}
    out = {}
    for g in lake.read("slv", "golden_party_scd2").filter("is_current AND status = 'ACTIVE'").collect():
        for t in json.loads(g["member_tokens"]):
            out[tok[t]] = g["golden_id"]
    return out


def test_partition_matches_the_independent_answer_key(lake, test_keys, gen_dir, manifest):
    rows = crm_rows(gen_dir)
    unrecoverable = set(ids_of(manifest, "D09")["ids"])
    third = ids_of(manifest, "D10")["id_less_third"]
    by_mobile = {}
    for r in rows:
        nid = validate_saudi_10digit_id(r["national_id"])
        if nid and r["mobile"]:
            by_mobile[canonical_phone(r["mobile"])] = (nid, bool(r["full_name_ar"]), bool(r["full_name_en"]))

    def idless_owner(r):
        """Documented rule: an ID-less record joins only when a name in the SAME script can be compared."""
        hit = by_mobile.get(canonical_phone(r["mobile"]))
        if hit and ((hit[1] and r["full_name_ar"]) or (hit[2] and r["full_name_en"])):
            return hit[0]
        return None
    truth = defaultdict(set)
    for r in rows:
        sid = r["source_customer_id"]
        if sid in unrecoverable or sid == third:
            continue
        person = (validate_saudi_10digit_id(r["national_id"]) or r["vat_number"]
                  or idless_owner(r) or sid)
        truth[person].add(sid)
    got = defaultdict(set)
    for sid, gid in current_members(lake, test_keys, gen_dir).items():
        got[gid].add(sid)
    assert sorted(map(sorted, truth.values())) == sorted(map(sorted, got.values()))


def test_five_spellings_one_golden_and_brothers_separate(lake, test_keys, gen_dir, manifest):
    m = current_members(lake, test_keys, gen_dir)
    five = ids_of(manifest, "D11")["ids"]
    assert len({m[s] for s in five}) == 1
    d10 = ids_of(manifest, "D10")
    a, b = d10["brothers"]
    assert m[a] != m[b]
    assert d10["id_less_third"] not in m
    conflicts = lake.read("quarantine", "mdm_match_conflicts").collect()
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["status"] == "OPEN" and c["conflict_type"] == "AMBIGUOUS_IDLESS_MATCH"
    assert c["subject_token_id"] == crypto.token_for(test_keys.hmac_key, d10["id_less_third"])
    assert set(json.loads(c["candidate_golden_ids"])) == {m[a], m[b]}


def test_golden_legal_name_survives_untouched_and_decrypts(lake, test_keys, gen_dir, manifest):
    m = current_members(lake, test_keys, gen_dir)
    gid = m[ids_of(manifest, "D11")["ids"][0]]
    g = lake.read("slv", "golden_party_scd2").filter(f"golden_id = '{gid}' AND is_current").first()
    assert g["member_count"] == 5 and g["anchor_id_type"] == "IQAMA"      # the ID starts with 2
    vault = {r["subject_token_id"]: bytes(r["wrapped_dek"]) for r in lake.read("security", "pii_vault_metadata")
             .filter(f"subject_token_id = '{g['name_ar_source_token']}'").collect()}
    dek = crypto.unwrap_dek(test_keys, g["name_ar_source_token"], vault[g["name_ar_source_token"]])
    name = crypto.decrypt_field(dek, g["name_ar_source_token"], "full_name_ar", g["name_ar_enc"])
    assert name == "\u0645\u062D\u0645\u062F \u0628\u0644\u0627\u0644 \u0627\u0644\u0639\u062A\u064A\u0628\u064A"


def test_mdm_tables_hold_no_cleartext_pii(lake, gen_dir):
    plain = set()
    for r in crm_rows(gen_dir):
        for col in ("full_name_ar", "full_name_en", "national_id", "mobile", "landline", "email",
                    "spl_short_address"):
            if r.get(col):
                plain.add(r[col])
    for r in read_csv(gen_dir / "crm/spl_address_observations.csv"):
        plain.update(v for v in (r["short_address"], r["building_number"], r["secondary_number"]) if v)
    for schema, table in MDM_TABLES:
        df = lake.read(schema, table)
        cols = [f.name for f in df.schema.fields if f.dataType.simpleString() == "string"]
        cells = {v for row in df.select(*cols).collect() for v in row if v}
        assert not cells & plain, (table, sorted(cells & plain)[:3])


def test_registry_and_addresses(lake):
    reg = lake.read("slv", "identifier_registry")
    types = {r["id_type"]: r["n"] for r in reg.groupBy("id_type").count().withColumnRenamed("count", "n").collect()}
    assert set(types) == {"NATIONAL_ID", "IQAMA", "VAT", "UNIFIED_700"}
    assert reg.filter("validation_status = 'INVALID_CHECKSUM'").count() == 0
    assert reg.groupBy("id_type", "identifier_hmac").count().filter("count > 1").count() == 0
    addr = lake.read("slv", "address_observations")
    assert addr.count() == 1000
    assert addr.filter("format_status <> 'VALID_4L4D'").count() == 0
    per_golden = addr.filter("golden_id IS NOT NULL").groupBy("golden_id").agg(
        {"is_current_for_golden": "max"}).collect()
    assert all(r[1] for r in per_golden)
    assert addr.filter("is_current_for_golden").groupBy("golden_id").count().filter("count > 1").count() == 0


def test_replay_is_idempotent(lake_run):
    first, replay = lake_run["first"]["mdm"], lake_run["replay"]["mdm"]
    assert first["ledger_events_appended"] == first["records"] - first["open_conflicts"]
    assert replay["ledger_events_appended"] == 0 and replay["versions_opened"] == 0
    assert replay["goldens"] == first["goldens"]


def test_steward_assign_then_unmerge_is_reversible_scd2(spark, lake_run, test_keys, gen_dir, manifest,
                                                         tmp_path_factory):
    from mizan.spark.lake import Lake, cleanup_staging
    from mizan.spark.mdm_land import apply_steward_decision
    from mizan.spark.session import TableLocator
    root = tmp_path_factory.mktemp("lake_steward")
    shutil.copytree(lake_run["root"], root, dirs_exist_ok=True)
    lk = Lake(spark, TableLocator("local", root))
    d10 = ids_of(manifest, "D10")
    third = crypto.token_for(test_keys.hmac_key, d10["id_less_third"])
    gid_a = current_members(lk, test_keys, gen_dir)[d10["brothers"][0]]

    stats = apply_steward_decision(lk, third, gid_a, "MERGE", "steward.najd", "customer confirmed by phone",
                                   test_keys)
    assert stats["open_conflicts"] == 0 and stats["versions_opened"] == 1 and stats["versions_closed"] == 1
    hist = {r["version"]: r for r in lk.read("slv", "golden_party_scd2").filter(f"golden_id = '{gid_a}'").collect()}
    assert hist[1]["is_current"] is False and hist[1]["valid_to"] is not None
    assert hist[2]["is_current"] and hist[2]["member_count"] == 2
    assert lk.read("quarantine", "mdm_match_conflicts").first()["status"] == "RESOLVED"

    apply_steward_decision(lk, third, gid_a, "UNMERGE", "steward.najd", "second call: different person", test_keys)
    hist = {r["version"]: r for r in lk.read("slv", "golden_party_scd2").filter(f"golden_id = '{gid_a}'").collect()}
    assert hist[3]["is_current"] and hist[3]["member_count"] == 1
    ledger = lk.read("slv", "entity_merge_ledger").filter(f"subject_token_id = '{third}'").orderBy("event_seq")
    assert [(r["action"], r["match_rule"], r["actor"]) for r in ledger.collect()] == [
        ("MERGE", "STEWARD_ASSIGN", "steward.najd"), ("UNMERGE", "STEWARD_UNMERGE", "steward.najd"),
        ("MERGE", "NEW_GOLDEN", "SYSTEM")]
    cleanup_staging(spark)
