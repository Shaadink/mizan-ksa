"""Score the MDM ladder against the generator's ground truth instead of describing it.

Until now the ladder's quality rested on one hard negative (the brothers) and one positive (five spellings of
one customer). Both are real, both matter, and neither is a measurement: a matcher that merged nothing at all
would pass the brother test, and a matcher that merged everything would pass the five-spellings test. External
review asked for the number, and the generator already knows the answer -- every CRM row carries a `_person`
index naming the real human behind it, so ground truth is free.

PAIRWISE SCORING, which is the standard for entity resolution. Take every pair of records that belongs to the
same real person (the truth) and every pair the ladder actually merged (the prediction):

    precision = merged pairs that are genuinely the same person / all merged pairs   -- false merges hurt this
    recall    = merged pairs that are genuinely the same person / all true pairs     -- missed merges hurt this

WHAT THIS PROJECT OPTIMISES, and it is not F1. A false merge joins two citizens into one identity: under PDPL
that is a personal-data incident, and in a tax context it corrupts an audit trail. A missed merge leaves two
rows for one person and a steward resolves it. The two errors are not symmetric, so the ladder is built to make
precision exactly 1.000 and let recall land where the evidence allows -- which is why cross-script records with
no typed identifier are routed to a human rather than guessed at. A fuzzy matcher would score a prettier F1 and
be the wrong tool.

The assertion is therefore: **precision == 1.000, no exceptions**, and recall is recorded rather than demanded.
"""

from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mizan.mdm import engine as E  # noqa: E402


def _hm(purpose: str, value: str) -> str:
    return hashlib.sha256(f"pr-test-key|{purpose}|{value}".encode()).hexdigest()


@pytest.fixture(scope="module")
def truth_and_records():
    """Rebuild the CRM in memory so `_person` survives: it is deliberately not written to the CSV."""
    import random

    from mizan.generator.build import Dataset, GenConfig, _build_crm, _build_parties, _build_reference

    cfg = GenConfig()
    rng = random.Random(cfg.seed)
    ds = Dataset(cfg)
    _build_reference(ds)
    _build_parties(ds, rng)
    _build_crm(ds, rng)

    records, truth = [], {}
    for source, rows in (("crm_pos", ds.crm_pos), ("crm_ecom", ds.crm_ecom)):
        for row in rows:
            if row["party_type"] != "PERSON":
                continue                      # organisations resolve on VAT/700, scored separately in the suite
            name_ar = row["full_name_ar"] or ""
            if name_ar and set(name_ar) == {"?"}:
                continue                      # the 15 unrecoverable rows are quarantined before MDM ever sees them
            token = _hm("subject", row["source_customer_id"])
            records.append(E.PartyRecord(
                token=token, source=source, party_type="PERSON", created_date=row["created_date"],
                name_ar=name_ar or None, name_en=row["full_name_en"] or None,
                national_id=row["national_id"] or None, mobile=row["mobile"] or None,
                landline=row["landline"] or None, city=row["city"] or None,
                name_ar_enc=f"ct:{token}:ar" if name_ar else None,
                name_en_enc=f"ct:{token}:en" if row["full_name_en"] else None))
            truth[token] = row["_person"]
    if len(records) < 100:
        pytest.skip("generator produced too few party records to score")
    return truth, records


@pytest.fixture(scope="module")
def scored(truth_and_records):
    truth, records = truth_and_records
    result = E.resolve(records, _hm)

    # True pairs: both records name the same real person. `_person is None` means the generator did not assign
    # one (walk-ins, the deliberately ambiguous third Qahtani), so those rows join no true pair.
    by_person = defaultdict(list)
    for token, person in truth.items():
        if person is not None:
            by_person[person].append(token)
    true_pairs = {frozenset(p) for members in by_person.values() for p in combinations(sorted(members), 2)}

    by_golden = defaultdict(list)
    for token, golden in result.membership.items():
        by_golden[golden].append(token)
    pred_pairs = {frozenset(p) for members in by_golden.values() for p in combinations(sorted(members), 2)}

    tp = len(true_pairs & pred_pairs)
    fp = len(pred_pairs - true_pairs)
    fn = len(true_pairs - pred_pairs)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"result": result, "records": records, "truth": truth, "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "false_merges": [tuple(sorted(p)) for p in list(pred_pairs - true_pairs)[:5]],
            "missed": [tuple(sorted(p)) for p in list(true_pairs - pred_pairs)[:5]]}


def test_precision_is_exactly_one_no_false_merges(scored, truth_and_records):
    """The non-negotiable half. One false merge is one PDPL incident; there is no acceptable rate above zero."""
    truth, _ = truth_and_records
    if scored["fp"]:
        offenders = [tuple(sorted((truth[a], truth[b]))) for a, b in scored["false_merges"]]
        pytest.fail(f"{scored['fp']} false merges -- two different people joined into one identity, "
                    f"by ground-truth person index: {offenders}")
    assert scored["precision"] == 1.0


def test_recall_is_recorded_not_demanded(scored):
    """Recall is an outcome of refusing to guess, so it is measured and printed, not asserted against a target.

    The floor exists only to catch a ladder that has stopped matching at all -- which would also pass the
    precision test above, and is exactly the failure a precision-only check cannot see.
    """
    s = scored
    print(f"\nMDM pairwise scoring against generator ground truth"
          f"\n  records scored   {len(s['records']):,}"
          f"\n  true pairs       {s['tp'] + s['fn']:,}"
          f"\n  merged pairs     {s['tp'] + s['fp']:,}"
          f"\n  true positives   {s['tp']:,}"
          f"\n  false merges     {s['fp']:,}   <- must be 0"
          f"\n  missed merges    {s['fn']:,}   <- steward queue, not error"
          f"\n  precision        {s['precision']:.4f}"
          f"\n  recall           {s['recall']:.4f}"
          f"\n  f1               {s['f1']:.4f}")
    assert s["recall"] > 0.5, "the ladder has stopped matching: perfect precision by doing nothing"


def test_the_brothers_are_still_apart_in_the_full_population(scored, truth_and_records):
    """The hard negative, re-run at population scale rather than in a three-record fixture.

    Persons 1 and 2 are brothers: same family name, different National IDs, and they share a landline. A fuzzy
    matcher merges them. If precision is 1.000 they cannot have been merged, but assert it directly so the
    scenario is named in the suite rather than implied by an aggregate.
    """
    truth, _ = truth_and_records
    result = scored["result"]
    brother_a = {t for t, p in truth.items() if p == 1}
    brother_b = {t for t, p in truth.items() if p == 2}
    if not (brother_a and brother_b):
        pytest.skip("brothers not present in this slice")
    goldens_a = {result.membership[t] for t in brother_a if t in result.membership}
    goldens_b = {result.membership[t] for t in brother_b if t in result.membership}
    assert goldens_a.isdisjoint(goldens_b), "the brothers were merged: a false merge across two citizens"
