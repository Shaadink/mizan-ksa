"""Module 4: bilingual party resolution with a Typed Identifier Registry and a reversible merge ledger.

Pure Python, no Spark: it receives DECRYPTED party records in memory and returns rows that hold no cleartext PII
(identifiers and phones as keyed HMACs, names only as the source ciphertext). `mizan.spark.mdm_land` feeds it from
brz.crm_party_raw and persists the result.

Matching ladder (deterministic, no fuzzy score):
  1. ANCHOR  - a checksum-valid National ID / Iqama (persons) or a format-valid VAT / 700 number (organisations).
               Records sharing an anchor merge. Two different valid IDs NEVER merge (hard-negative rule, I-09).
  2. ID-LESS - a record without an anchor joins a golden profile only if its name is compatible AND it shares a
               phone with EXACTLY ONE candidate. Two or more candidates -> quarantine.mdm_match_conflicts
               (steward queue), never auto-merged. Zero candidates -> its own golden profile.
  3. STEWARD - decisions recorded in slv.entity_merge_ledger with actor != SYSTEM pin that record; re-runs respect
               them. Every merge is reversible by an UNMERGE ledger row (I-10).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from mizan.mdm.arabic_norm_and_privacy import (
    ARABIC_INDIC_MAP,
    build_arabic_search_key,
    validate_saudi_10digit_id,
    validate_unified_700,
    validate_vat_number,
)

SEARCH_KEY_VERSION = "SK_V1"
SYSTEM = "SYSTEM"

ID_TYPES = ("NATIONAL_ID", "IQAMA", "VAT", "UNIFIED_700")
VALIDATION_STATUSES = ("VALID_CHECKSUM", "INVALID_CHECKSUM", "VALID_FORMAT", "FORMAT_ONLY", "INVALID_FORMAT")
MATCH_RULES = ("ANCHOR_NATIONAL_ID", "ANCHOR_IQAMA", "ANCHOR_VAT", "ANCHOR_UNIFIED_700", "NAME_PHONE_UNIQUE",
               "NEW_GOLDEN", "STEWARD_ASSIGN", "STEWARD_UNMERGE", "SYSTEM_RECOMPUTE")
CONFLICT_TYPES = ("AMBIGUOUS_IDLESS_MATCH", "IDENTIFIER_COLLISION")
PARTY_TYPES = ("PERSON", "ORGANIZATION")
# survivorship: a clean source beats a repaired one; '?????' never reaches MDM (quarantined at Bronze)
_ENCODING_RANK = {"CLEAN": 0, "DECODED_CP1256": 0, "REPAIRED_MOJIBAKE": 1}

Hmac = Callable[[str, str], str]   # (purpose, canonical value) -> keyed hex digest


@dataclass(frozen=True)
class PartyRecord:
    """One decrypted CRM record. `*_enc` are the Bronze ciphertexts, carried through for survivorship."""
    token: str
    source: str
    party_type: str
    created_date: str
    name_ar: str | None = None
    name_en: str | None = None
    national_id: str | None = None
    mobile: str | None = None
    landline: str | None = None
    vat_number: str | None = None
    unified_700: str | None = None
    city: str | None = None
    name_encoding_status: str | None = None
    name_ar_enc: str | None = None
    name_en_enc: str | None = None


@dataclass
class TypedId:
    id_type: str
    canonical: str | None
    status: str
    is_anchor: bool


@dataclass
class MdmResult:
    membership: dict[str, str]                       # token -> golden_id (current)
    goldens: list[dict]                              # current golden attributes (one per golden_id)
    registry: list[dict]                             # slv.identifier_registry
    ledger_new: list[dict]                           # rows to APPEND to slv.entity_merge_ledger
    conflicts: list[dict]                            # quarantine.mdm_match_conflicts (OPEN or RESOLVED)
    stats: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- typing & normalisation

def canonical_phone(raw: str | None) -> str | None:
    s = re.sub(r"\D", "", (raw or "").translate(ARABIC_INDIC_MAP))
    if s.startswith("00966"):
        s = "0" + s[5:]
    elif s.startswith("966"):
        s = "0" + s[3:]
    return s if len(s) >= 9 else None


def type_identifiers(r: PartyRecord) -> list[TypedId]:
    """Typed Identifier Registry rules: 1x/2x Modulo-10 checksum, VAT 3..3 (15 digits), 700 format-only."""
    out: list[TypedId] = []
    if r.national_id and r.national_id.strip():
        valid = validate_saudi_10digit_id(r.national_id)
        if valid:
            out.append(TypedId("NATIONAL_ID" if valid[0] == "1" else "IQAMA", valid, "VALID_CHECKSUM",
                               r.party_type == "PERSON"))
        else:
            raw = r.national_id.strip().translate(ARABIC_INDIC_MAP)
            t = "IQAMA" if raw.startswith("2") else "NATIONAL_ID"
            out.append(TypedId(t, raw, "INVALID_CHECKSUM", False))
    if r.vat_number and r.vat_number.strip():
        v = validate_vat_number(r.vat_number)
        out.append(TypedId("VAT", v or r.vat_number.strip(), "VALID_FORMAT" if v else "INVALID_FORMAT",
                           bool(v) and r.party_type == "ORGANIZATION"))
    if r.unified_700 and r.unified_700.strip():
        u = validate_unified_700(r.unified_700)
        out.append(TypedId("UNIFIED_700", u or r.unified_700.strip(), "FORMAT_ONLY" if u else "INVALID_FORMAT",
                           bool(u) and r.party_type == "ORGANIZATION"))
    return out


def primary_anchor(ids: list[TypedId]) -> TypedId | None:
    order = {"NATIONAL_ID": 0, "IQAMA": 0, "VAT": 1, "UNIFIED_700": 2}
    anchors = sorted((i for i in ids if i.is_anchor), key=lambda i: order[i.id_type])
    return anchors[0] if anchors else None


def name_keys(r: PartyRecord) -> tuple[str | None, str | None]:
    ar = build_arabic_search_key(r.name_ar) if r.name_ar else None
    en = build_arabic_search_key(r.name_en) if r.name_en else None   # same ladder folds case/punctuation
    return ar or None, en or None


def _tokens_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return False
    for x, y in zip(ta, tb, strict=True):
        if x == y:
            continue
        if (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)):   # initial: 'A.' ~ 'Ali'
            continue
        return False
    return True


def names_compatible(a: tuple[str | None, str | None], b: tuple[str | None, str | None]) -> bool:
    """Compare within a script only (Arabic with Arabic, English with English); never transliterate."""
    for x, y in zip(a, b, strict=True):
        if x and y and _tokens_compatible(x, y):
            return True
    return False


def golden_id_for(seed: str) -> str:
    return "GP-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16].upper()


def _event_id(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:24]


# ----------------------------------------------------------------------------- ledger replay

def membership_from_ledger(ledger: Iterable[dict]) -> tuple[dict[str, str], set[str]]:
    """Fold the ledger in event order -> (current membership, tokens pinned by a steward)."""
    members: dict[str, str] = {}
    pinned: set[str] = set()
    for e in sorted(ledger, key=lambda e: (e["event_seq"], e["merge_event_id"])):
        if e["action"] == "MERGE":
            members[e["subject_token_id"]] = e["golden_id"]
        elif e["action"] == "UNMERGE" and members.get(e["subject_token_id"]) == e["golden_id"]:
            del members[e["subject_token_id"]]
        if e["actor"] != SYSTEM:
            pinned.add(e["subject_token_id"])
    return members, pinned


# ----------------------------------------------------------------------------- resolution

def resolve(records: list[PartyRecord], hmac: Hmac, prior_ledger: list[dict] | None = None,
            prior_conflicts: list[dict] | None = None, now: str = "1970-01-01T00:00:00") -> MdmResult:
    prior_ledger = prior_ledger or []
    prior_members, pinned = membership_from_ledger(prior_ledger)
    seq0 = max((e["event_seq"] for e in prior_ledger), default=0)
    for r in records:
        if r.party_type not in PARTY_TYPES:
            raise ValueError(f"unknown party_type {r.party_type!r}")
    recs = sorted(records, key=lambda r: r.token)
    by_token = {r.token: r for r in recs}
    typed = {r.token: type_identifiers(r) for r in recs}
    keys = {r.token: name_keys(r) for r in recs}
    phones = {r.token: {hmac("PHONE", p) for p in (canonical_phone(r.mobile), canonical_phone(r.landline)) if p}
              for r in recs}

    target: dict[str, tuple[str, str, str]] = {}      # token -> (golden_id, rule, evidence)
    conflicts: dict[str, dict] = {}
    anchor_of: dict[str, tuple[str, str]] = {}        # golden_id -> (anchor id_type, anchor hmac)
    golden_members: dict[str, list[str]] = {}

    def assign(token: str, gid: str, rule: str, evidence: str) -> None:
        target[token] = (gid, rule, evidence)
        golden_members.setdefault(gid, []).append(token)

    # 0. steward-pinned records keep their ledger membership
    for t in recs:
        if t.token in pinned:
            if t.token in prior_members:
                assign(t.token, prior_members[t.token], "STEWARD_ASSIGN", "steward decision")
            else:      # unmerged by a steward: stands alone, never silently re-merged by the anchor rule
                assign(t.token, golden_id_for(f"RECORD|{t.token}"), "NEW_GOLDEN", "steward split")

    # 1. anchors
    for r in recs:
        if r.token in target:
            continue
        a = primary_anchor(typed[r.token])
        if a is None:
            continue
        ah = hmac(a.id_type, a.canonical)   # same purpose labels as Bronze national_id_hmac
        gid = golden_id_for(f"ANCHOR|{a.id_type}|{ah}")
        anchor_of.setdefault(gid, (a.id_type, ah))
        assign(r.token, gid, f"ANCHOR_{a.id_type}", f"{a.id_type} {a.status}")

    # registry: one row per (id_type, identifier) -> golden; collisions are conflicts, never merges
    registry: dict[tuple[str, str], dict] = {}
    for r in recs:
        if r.token not in target:
            continue
        gid = target[r.token][0]
        for i in typed[r.token]:
            ih = hmac(i.id_type, i.canonical)
            row = registry.get((i.id_type, ih))
            if row is None:
                registry[(i.id_type, ih)] = {"id_type": i.id_type, "identifier_hmac": ih, "golden_id": gid,
                                             "validation_status": i.status, "is_anchor": i.is_anchor,
                                             "record_count": 1}
            elif row["golden_id"] != gid:
                cid = _event_id("IDENTIFIER_COLLISION", r.token, i.id_type, ih)
                conflicts[cid] = {"conflict_id": cid, "subject_token_id": r.token,
                                  "conflict_type": "IDENTIFIER_COLLISION",
                                  "candidate_golden_ids": json.dumps(sorted({row["golden_id"], gid})),
                                  "evidence": f"{i.id_type} already registered to another golden profile"}
            else:
                row["record_count"] += 1

    # 2. ID-less records: name-compatible AND phone-sharing with exactly one golden profile
    def candidates(r: PartyRecord) -> list[str]:
        out = []
        for gid, toks in golden_members.items():
            m = [by_token[t] for t in toks if t in by_token]
            if not m or m[0].party_type != r.party_type:
                continue
            if not any(phones[r.token] & phones[x.token] for x in m):
                continue
            if any(names_compatible(keys[r.token], keys[x.token]) for x in m):
                out.append(gid)
        return sorted(out)

    for r in recs:
        if r.token in target:
            continue
        cands = candidates(r)
        if len(cands) == 1:
            assign(r.token, cands[0], "NAME_PHONE_UNIQUE", "name compatible + shared phone, single candidate")
        elif len(cands) > 1:
            cid = _event_id("AMBIGUOUS_IDLESS_MATCH", r.token)
            conflicts[cid] = {"conflict_id": cid, "subject_token_id": r.token,
                              "conflict_type": "AMBIGUOUS_IDLESS_MATCH",
                              "candidate_golden_ids": json.dumps(cands),
                              "evidence": f"no anchor; name + phone match {len(cands)} golden profiles"}
        else:
            assign(r.token, golden_id_for(f"RECORD|{r.token}"), "NEW_GOLDEN", "no anchor, no candidate")

    # 3. ledger delta against the prior membership (idempotent re-runs append nothing)
    ledger_new: list[dict] = []
    seq = seq0

    def emit(token: str, gid: str, action: str, rule: str, evidence: str, actor: str = SYSTEM) -> None:
        nonlocal seq
        seq += 1
        ledger_new.append({"merge_event_id": _event_id(seq, token, gid, action, rule), "event_seq": seq,
                           "golden_id": gid, "subject_token_id": token, "action": action, "match_rule": rule,
                           "evidence": evidence, "actor": actor, "event_ts": now})

    for t in sorted(set(prior_members) | set(target)):
        old, new = prior_members.get(t), target.get(t, (None, None, None))[0]
        if old == new:
            continue
        if old is not None:
            emit(t, old, "UNMERGE", "SYSTEM_RECOMPUTE", "membership recomputed")
        if new is not None:
            _, rule, ev = target[t]
            emit(t, new, "MERGE", rule, ev)

    # conflicts already resolved by a steward stay RESOLVED; still-open ones are not duplicated
    prior_c = {c["conflict_id"]: c for c in (prior_conflicts or [])}
    out_conflicts = []
    for cid, c in sorted(conflicts.items()):
        if c["subject_token_id"] in pinned:
            continue
        out_conflicts.append({**c, "status": prior_c.get(cid, {}).get("status", "OPEN"),
                              "detected_at": prior_c.get(cid, {}).get("detected_at", now)})
    for cid, c in sorted(prior_c.items()):
        if cid not in conflicts or c["subject_token_id"] in pinned:
            out_conflicts.append({**c, "status": "RESOLVED"})

    membership = {t: v[0] for t, v in target.items()}
    goldens = [_survive(gid, [by_token[t] for t in sorted(toks) if t in by_token], anchor_of.get(gid))
               for gid, toks in sorted(golden_members.items())]
    stats = {"records": len(recs), "goldens": len(goldens),
             "anchored_records": sum(1 for v in target.values() if v[1].startswith("ANCHOR_")),
             "idless_attached": sum(1 for v in target.values() if v[1] == "NAME_PHONE_UNIQUE"),
             "new_goldens_without_anchor": sum(1 for v in target.values() if v[1] == "NEW_GOLDEN"),
             "open_conflicts": sum(1 for c in out_conflicts if c["status"] == "OPEN"),
             "ledger_events_appended": len(ledger_new)}
    return MdmResult(membership, goldens, sorted(registry.values(), key=lambda x: (x["id_type"],
                     x["identifier_hmac"])), ledger_new, out_conflicts, stats)


_DECORATION_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640\uFB50-\uFDFF\uFE70-\uFEFF]")


def _decorated(name: str | None) -> int:
    """1 if the text carries tashkeel, tatweel or presentation-form ligatures: a plain spelling is preferred."""
    return 1 if name and _DECORATION_RE.search(name) else 0


def _survive(gid: str, members: list[PartyRecord], anchor: tuple[str, str] | None) -> dict:
    """Survivorship: Arabic legal name from the cleanest source (raw text untouched, still encrypted);
    English name with the most words (full over abbreviated); ties -> oldest record, then token."""
    ar = sorted((m for m in members if m.name_ar_enc),
                key=lambda m: (_ENCODING_RANK.get(m.name_encoding_status or "CLEAN", 2), _decorated(m.name_ar),
                               m.created_date, m.token))
    en = sorted((m for m in members if m.name_en_enc),
                key=lambda m: (-len((m.name_en or "").split()), m.created_date, m.token))
    cities = sorted({m.city for m in members if m.city})
    return {"golden_id": gid, "party_type": members[0].party_type,
            "anchor_id_type": anchor[0] if anchor else None, "anchor_hmac": anchor[1] if anchor else None,
            "member_tokens": json.dumps(sorted(m.token for m in members)), "member_count": len(members),
            "name_ar_enc": ar[0].name_ar_enc if ar else None, "name_ar_source_token": ar[0].token if ar else None,
            "name_en_enc": en[0].name_en_enc if en else None, "name_en_source_token": en[0].token if en else None,
            "city": cities[0] if len(cities) == 1 else (",".join(cities) if cities else None)}


# ----------------------------------------------------------------------------- steward actions (reversible)

def steward_event(prior_ledger: list[dict], token: str, golden_id: str, action: str, actor: str,
                  reason: str, now: str) -> dict:
    """A steward ASSIGNs a quarantined record to a golden profile, or UNMERGEs a record from one."""
    if action not in ("MERGE", "UNMERGE"):
        raise ValueError(f"unknown steward action {action!r}")
    if actor == SYSTEM:
        raise ValueError("steward actions need a named actor")
    seq = max((e["event_seq"] for e in prior_ledger), default=0) + 1
    rule = "STEWARD_ASSIGN" if action == "MERGE" else "STEWARD_UNMERGE"
    return {"merge_event_id": _event_id(seq, token, golden_id, action, rule), "event_seq": seq,
            "golden_id": golden_id, "subject_token_id": token, "action": action, "match_rule": rule,
            "evidence": reason, "actor": actor, "event_ts": now}
