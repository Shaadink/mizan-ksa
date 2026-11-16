"""Deterministic ~100K-row source generator for MIZAN-KSA (spec Day-1 volumes, Section 7.1 keys).

Same seed -> byte-identical files. Rules that keep it deterministic:
  * one random.Random(seed); stdlib only; never iterate a set; every output sorted before writing;
  * no wall-clock time anywhere; CSV with '\n' line endings; JSON with sort_keys.

What it writes (all "source system" files, i.e. BEFORE Bronze; Bronze encrypts PII on landing):
  orders/commerce_events.csv          25,000  1 row per order event (ORDER_PLACED / RETURN_REQUESTED)
  zatca/invoice_requests.jsonl        25,000  unsigned invoice + credit-note requests from POS/e-com
  payments/payment_events.csv         18,000  CAPTURE / REFUND / CHARGEBACK, amounts positive
  settlement/NAJDACQ_SETTLEMENT_*.csv 17,000  bank T+1 files (fees from the bank), last day in transit
  erp/erp_gl_acdoca.csv               ~10,000 ACDOCA-shaped, store x day x GL account
  crm/*.csv                           5,000   POS CRM (real Windows-1256), e-com CRM (UTF-8), SPL obs.
  demo/*                              overlay rows for the recon circuit-breaker demo (orphan, 0.01)
  zatca/fatoora_fault_plan.json, defect_manifest.json, _control.json, reference/*.csv
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from mizan.common.money import ZERO, fmt_sar, q2
from mizan.common.saudi_ids import mint_saudi_id, mint_unified_700, mint_vat_number, to_arabic_indic
from mizan.generator import catalog as cat

KSA = timezone(timedelta(hours=3))  # Asia/Riyadh has no DST; fixed +03:00 is exact
DEFAULT_SEED = 20261112


@dataclass(frozen=True)
class GenConfig:
    seed: int = DEFAULT_SEED
    start: date = date(2026, 2, 12)
    days: int = 20
    ramadan_start: date = date(2026, 2, 18)  # traffic shape only; calendar truth lives in dim_date_saudi
    n_stores: int = 120
    n_registers: int = 400
    captures: int = 16_200
    refunds: int = 1_500
    chargebacks: int = 300
    cash_orders: int = 7_300
    ecom_capture_share: Decimal = Decimal("0.65")
    last_day_counts: tuple[int, int, int] = (900, 80, 20)  # captures, refunds, chargebacks -> 1,000 IN_TRANSIT
    n_persons: int = 2_600
    crm_pos: int = 1_800
    crm_ecom: int = 2_200
    address_obs: int = 1_000
    b2b_share: float = 0.08
    walk_in_share: float = 0.30
    n_mojibake: int = 40
    n_unrecoverable: int = 15
    indic_digit_share: float = 0.03
    tape_egs: str = "EGS-05"
    tamper_egs: str = "EGS-03"
    tamper_icv: int = 500
    resend_payout_offset: int = 8  # D07: this payout day's bank file is delivered twice

    @property
    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]


# ----------------------------------------------------------------------------- helpers

def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _weighted(rng: random.Random, pairs) -> str:
    total = sum(w for _, w in pairs)
    r = rng.random() * total
    for value, w in pairs:
        r -= w
        if r < 0:
            return value
    return pairs[-1][0]


def allocate(total: int, weights: list[float]) -> list[int]:
    """Largest-remainder split of an integer total by weights (deterministic, exact sum)."""
    s = sum(weights)
    raw = [total * w / s for w in weights]
    out = [math.floor(x) for x in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - out[i]), i))
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def mojibake(text: str) -> str:
    """What a CP1256 export looks like after being read as CP1252 (latin-1 for its 5 holes)."""
    out = []
    for b in text.encode("cp1256"):
        try:
            out.append(bytes([b]).decode("cp1252"))
        except UnicodeDecodeError:
            out.append(chr(b))
    return "".join(out)


def utc_iso(dt_ksa: datetime) -> str:
    return dt_ksa.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_STORE_HOURS = [(h, w) for h, w in zip(range(9, 24), (2, 3, 4, 5, 6, 6, 5, 5, 6, 7, 8, 9, 9, 8, 6), strict=True)]
_STORE_HOURS_RAMADAN = [(h, w) for h, w in zip(
    (0, 1, 10, 11, 12, 13, 14, 15, 16, 17, 20, 21, 22, 23),
    (8, 4, 1, 2, 2, 2, 3, 4, 6, 9, 10, 12, 12, 11), strict=True)]
_ECOM_HOURS = [(h, 2 + (6 if 19 <= h <= 23 else 0) + (3 if 0 <= h <= 1 else 0)) for h in range(24)]


def _pick_ts(rng: random.Random, d: date, channel: str, ramadan: bool) -> datetime:
    hours = _ECOM_HOURS if channel == "ECOM" else (_STORE_HOURS_RAMADAN if ramadan else _STORE_HOURS)
    h = _weighted(rng, hours)
    return datetime.combine(d, time(h, rng.randrange(60), rng.randrange(60)), tzinfo=KSA)


# ----------------------------------------------------------------------------- domain records

@dataclass
class Person:
    idx: int
    name_ar: str
    name_en: str
    national_id: str
    mobile: str
    landline: str
    city_i: int
    short_address: str


@dataclass
class Org:
    idx: int
    name_ar: str
    name_en: str
    vat_number: str
    unified_700: str
    city_i: int


@dataclass
class Order:
    key: int
    channel: str
    store_id: str
    register_id: str
    merchant_id: str
    egs_id: str
    ts: datetime
    payment_means: str
    scheme: str | None
    flow: str
    customer_ref: str
    buyer_name: str
    buyer_mobile: str
    delivery_addr: str
    buyer_org: Org | None
    lines: list[dict]
    net: Decimal = ZERO
    vat: Decimal = ZERO
    order_id: str = ""
    invoice_uuid: str = ""
    request_id: str = ""
    refunded_or_disputed: bool = False

    @property
    def total(self) -> Decimal:
        return self.net + self.vat


@dataclass
class Return:
    order: Order
    ts: datetime
    line: dict
    net: Decimal
    vat: Decimal
    credit_note_uuid: str
    return_id: str = ""
    request_id: str = ""

    @property
    def total(self) -> Decimal:
        return self.net + self.vat


@dataclass
class PaymentEvent:
    event_type: str
    order: Order
    ts: datetime
    amount: Decimal
    credit_note_uuid: str = ""
    payment_event_id: str = ""


@dataclass
class Dataset:
    cfg: GenConfig
    stores: list[dict] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    orgs: list[Org] = field(default_factory=list)
    crm_pos: list[dict] = field(default_factory=list)
    crm_ecom: list[dict] = field(default_factory=list)
    addr_obs: list[dict] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    returns: list[Return] = field(default_factory=list)
    payments: list[PaymentEvent] = field(default_factory=list)
    defects: list[dict] = field(default_factory=list)


# ----------------------------------------------------------------------------- builders

def _build_reference(ds: Dataset) -> None:
    cfg = ds.cfg
    regs_per_store = allocate(cfg.n_registers, [1.0] * cfg.n_stores)
    for s in range(1, cfg.n_stores + 1):
        egs = f"EGS-0{(s - 1) * 4 // cfg.n_stores + 1}"
        ds.stores.append({
            "store_id": f"ST{s:03d}", "merchant_id": f"MID{100000 + s}", "channel": "POS",
            "egs_id": egs, "city": cat.CITIES[(s - 1) % len(cat.CITIES)][1],
            "registers": [f"ST{s:03d}-R{r:02d}" for r in range(1, regs_per_store[s - 1] + 1)],
        })


ECOM_MID, ECOM_STORE, ECOM_EGS = "MID900001", "ECOM", "EGS-05"
_REGION = ("R", "J", "D", "K", "M")
_LETTERS = "ABCDEFGHJKLMNPRSTWXYZ"


def _short_address(rng: random.Random, city_i: int) -> str:
    return _REGION[city_i] + "".join(rng.choice(_LETTERS) for _ in range(3)) + f"{rng.randrange(1000, 10000)}"


def _build_parties(ds: Dataset, rng: random.Random) -> None:
    cfg = ds.cfg
    seen_ids: set[str] = set()  # membership only, never iterated

    def unique_id(prefix: str) -> str:
        while True:
            v = mint_saudi_id(rng, prefix)
            if v not in seen_ids:
                seen_ids.add(v)
                return v

    for i in range(cfg.n_persons):
        female = rng.random() < 0.35
        first = rng.choice(cat.FEMALE_FIRST if female else cat.MALE_FIRST)
        father = rng.choice(cat.MALE_FIRST)
        family = rng.choice(cat.FAMILY)
        city_i = rng.randrange(len(cat.CITIES))
        ds.persons.append(Person(
            idx=i, name_ar=f"{first[0]} {father[0]} {family[0]}", name_en=f"{first[1]} {father[1]} {family[1]}",
            national_id=unique_id("1" if rng.random() < 0.85 else "2"),
            mobile="05" + "".join(str(rng.randrange(10)) for _ in range(8)),
            landline=("011" + "".join(str(rng.randrange(10)) for _ in range(7))) if rng.random() < 0.3 else "",
            city_i=city_i, short_address=_short_address(rng, city_i)))
    # person 0 = the 5-spelling golden customer; persons 1/2 = brothers sharing father's name + landline
    g = ds.persons[0]
    g.name_ar, g.name_en, g.city_i = cat.GOLDEN[0][0], cat.GOLDEN[0][1], 0
    shared_landline = "0114567890"
    for p, (ar, en) in zip(ds.persons[1:3], cat.BROTHERS, strict=True):
        p.name_ar, p.name_en, p.landline, p.city_i = ar, en, shared_landline, 0
    k = 0
    for form_ar, form_en in cat.ORG_FORMS:
        for word_ar, word_en in cat.ORG_WORDS:
            ds.orgs.append(Org(idx=k, name_ar=form_ar.format(word_ar), name_en=form_en.format(word_en),
                               vat_number=mint_vat_number(rng), unified_700=mint_unified_700(rng),
                               city_i=rng.randrange(len(cat.CITIES))))
            k += 1


def _crm_row(source: str, n: int, *, party_type="PERSON", name_ar="", name_en="", national_id="", mobile="",
             landline="", email="", vat_number="", unified_700="", short_address="", city="",
             created: date, person_idx: int | None) -> dict:
    return {"source_customer_id": f"{source}-C{n:06d}", "party_type": party_type, "full_name_ar": name_ar,
            "full_name_en": name_en, "national_id": national_id, "mobile": mobile, "landline": landline,
            "email": email, "vat_number": vat_number, "unified_700": unified_700,
            "spl_short_address": short_address, "city": city, "created_date": created.isoformat(),
            "_person": person_idx}


def _build_crm(ds: Dataset, rng: random.Random) -> None:
    cfg = ds.cfg
    P = ds.persons
    created = lambda: cfg.start - timedelta(days=rng.randrange(30, 1500))  # noqa: E731
    city = lambda p: cat.CITIES[p.city_i][1]  # noqa: E731
    g, ba, bb = P[0], P[1], P[2]

    # ---- POS CRM (exported by the legacy POS as real Windows-1256 bytes)
    pos: list[dict] = []
    pos.append(_crm_row("POS", 0, name_ar=g.name_ar, national_id=g.national_id, mobile=g.mobile,
                        short_address=g.short_address, city=city(g), created=created(), person_idx=0))
    pos.append(_crm_row("POS", 0, name_en="Mohd Otaibi", national_id=g.national_id, mobile=g.mobile,
                        created=created(), person_idx=0))
    pos.append(_crm_row("POS", 0, name_ar=ba.name_ar, name_en=ba.name_en, national_id=ba.national_id,
                        mobile=ba.mobile, landline=ba.landline, short_address=ba.short_address, city=city(ba),
                        created=created(), person_idx=1))
    third_ar = "\u0639. \u0639\u0628\u062F\u0627\u0644\u0644\u0647 \u0627\u0644\u0642\u062D\u0637\u0627\u0646\u064A"
    pos.append(_crm_row("POS", 0, name_ar=third_ar, name_en="A. Abdullah Al Qahtani", landline=ba.landline,
                        city=city(ba), created=created(), person_idx=None))
    for o in ds.orgs:
        pos.append(_crm_row("POS", 0, party_type="ORGANIZATION", name_ar=o.name_ar, name_en=o.name_en,
                            vat_number=o.vat_number, unified_700=o.unified_700, city=cat.CITIES[o.city_i][1],
                            created=created(), person_idx=None))
    special_pos = len(pos)
    for i in rng.sample(range(3, len(P)), cfg.crm_pos - special_pos):
        p = P[i]
        pos.append(_crm_row("POS", 0, name_ar=p.name_ar, name_en=p.name_en if rng.random() < 0.4 else "",
                            national_id=p.national_id if rng.random() < 0.8 else "", mobile=p.mobile,
                            landline=p.landline, short_address=p.short_address, city=city(p),
                            created=created(), person_idx=i))
    # D09: literal '?????' from a lossy legacy export: unrecoverable -> quarantine
    unrec = rng.sample(range(special_pos, len(pos)), cfg.n_unrecoverable)
    for j in sorted(unrec):
        pos[j]["full_name_ar"] = "?" * len(pos[j]["full_name_ar"])
        pos[j]["full_name_en"] = ""
    for n, row in enumerate(pos, start=1):
        row["source_customer_id"] = f"POS-C{n:06d}"
    ds.crm_pos = pos

    # ---- E-commerce CRM (UTF-8)
    eco: list[dict] = []
    tashkeel_lig = ("\u0645\u064F\u062D\u064E\u0645\u0651\u064E\u062F \u0628\uFEFB\u0644 "
                    "\u0627\u0644\u0639\u064F\u062A\u064E\u064A\u0652\u0628\u0650\u064A")
    eco.append(_crm_row("ECOM", 0, name_ar=mojibake(g.name_ar), national_id=g.national_id, mobile=g.mobile,
                        email="m.otaibi@example.com", created=created(), person_idx=0))
    eco.append(_crm_row("ECOM", 0, name_ar=tashkeel_lig, national_id=to_arabic_indic(g.national_id),
                        mobile=g.mobile, short_address=g.short_address, city=city(g), created=created(),
                        person_idx=0))
    eco.append(_crm_row("ECOM", 0, name_en=g.name_en, national_id=g.national_id, mobile=g.mobile,
                        email="mohammed.bilal@example.com", created=created(), person_idx=0))
    eco.append(_crm_row("ECOM", 0, name_ar=bb.name_ar, name_en=bb.name_en, national_id=bb.national_id,
                        mobile=bb.mobile, landline=bb.landline, short_address=bb.short_address, city=city(bb),
                        created=created(), person_idx=2))
    special_eco = len(eco)
    for i in rng.sample(range(3, len(P)), cfg.crm_ecom - special_eco):
        p = P[i]
        nid = p.national_id
        if rng.random() < cfg.indic_digit_share:
            nid = to_arabic_indic(nid)
        eco.append(_crm_row("ECOM", 0, name_ar=p.name_ar if rng.random() < 0.7 else "", name_en=p.name_en,
                            national_id=nid, mobile=p.mobile, email=f"user{i:05d}@example.com",
                            short_address=p.short_address, city=city(p), created=created(), person_idx=i))
    moj = rng.sample([j for j in range(special_eco, len(eco)) if eco[j]["full_name_ar"]], cfg.n_mojibake)
    for j in sorted(moj):
        eco[j]["full_name_ar"] = mojibake(eco[j]["full_name_ar"])
    for n, row in enumerate(eco, start=1):
        row["source_customer_id"] = f"ECOM-C{n:06d}"
    ds.crm_ecom = eco

    ds.defects += [
        {"id": "D08", "name": "CP1256_MOJIBAKE", "module": "M3/M4",
         "description": "POS CRM file is real Windows-1256 bytes (case 1); e-com CRM rows carry CP1256 text "
                        "mis-decoded as CP1252 (case 2), repaired with a round-trip check.",
         "location": {"file": "crm/crm_pos_cp1256.csv + crm/crm_ecom_utf8.csv",
                      "mojibake_ids": [eco[j]["source_customer_id"] for j in sorted(moj)]
                      + [eco[0]["source_customer_id"]]},
         "expected_handling": "decode in Python (not Spark CSV option); repaired text in slv", "invariants": []},
        {"id": "D09", "name": "CP1256_UNRECOVERABLE_QMARKS", "module": "M3/M4",
         "description": "Literal '?????' names from a lossy legacy export (case 3).",
         "location": {"file": "crm/crm_pos_cp1256.csv",
                      "ids": [pos[j]["source_customer_id"] for j in sorted(unrec)]},
         "expected_handling": "route to quarantine.schema_rejections; never guessed", "invariants": []},
        {"id": "D10", "name": "BROTHER_HARD_NEGATIVE", "module": "M4",
         "description": "Two brothers share father's name, family name and home landline but have different "
                        "valid National IDs; a third record with no ID matches both on name + landline.",
         "location": {"brothers": [pos[2]["source_customer_id"], eco[3]["source_customer_id"]],
                      "id_less_third": pos[3]["source_customer_id"]},
         "expected_handling": "brothers never merge; third -> quarantine.mdm_match_conflicts (steward)",
         "invariants": ["I-09"]},
        {"id": "D11", "name": "FIVE_SPELLINGS_ONE_CUSTOMER", "module": "M4",
         "description": "One customer in 5 surface spellings: raw CP1256 Arabic, CP1252 mojibake, tashkeel + "
                        "U+FEFB ligature with Arabic-Indic ID digits, full English, abbreviated English.",
         "location": {"ids": [pos[0]["source_customer_id"], pos[1]["source_customer_id"],
                              eco[0]["source_customer_id"], eco[1]["source_customer_id"],
                              eco[2]["source_customer_id"]]},
         "expected_handling": "all 5 merge into 1 golden id via the checksum-valid National ID anchor",
         "invariants": ["I-09", "I-10"]},
    ]

    # ---- SPL short-address observations (4 letters + 4 digits)
    obs: list[dict] = []
    known = [r for r in pos + eco if r["_person"] is not None and r["spl_short_address"]]
    obs.append({"source_system": "DELIVERY", "source_customer_id": eco[1]["source_customer_id"],
                "short_address": _short_address(rng, 0), "observed_date": (cfg.start + timedelta(days=3))})
    for r in rng.sample(known, cfg.address_obs - 1):
        sa = r["spl_short_address"]
        u = rng.random()
        if u < 0.06:   # moved: a new address observation
            sa = _short_address(rng, ds.persons[r["_person"]].city_i)
        elif u < 0.09:  # formatting noise a normaliser must handle (not a planted defect)
            sa = sa[:4].lower() + " " + sa[4:]
        obs.append({"source_system": rng.choice(("DELIVERY", "POS", "ECOM")),
                    "source_customer_id": r["source_customer_id"], "short_address": sa,
                    "observed_date": cfg.start - timedelta(days=rng.randrange(0, 400))})
    for n, o in enumerate(obs, start=1):
        city_i = _REGION.index(o["short_address"][0].upper())
        o.update({"observation_id": f"SPL-O{n:06d}", "building_number": f"{rng.randrange(1000, 10000)}",
                  "secondary_number": f"{rng.randrange(1000, 10000)}",
                  "district": cat.DISTRICTS[rng.randrange(len(cat.DISTRICTS))][1],
                  "city": cat.CITIES[city_i][1], "postal_code": f"{rng.randrange(11000, 35000)}",
                  "observed_date": o["observed_date"].isoformat()})
    ds.addr_obs = obs


def _make_lines(rng: random.Random, channel: str) -> list[dict]:
    idx_pool = cat.ECOM_ITEM_IDX if channel == "ECOM" else cat.STORE_ITEM_IDX
    n = _weighted(rng, ((1, 45), (2, 30), (3, 15), (4, 10)))
    lines = []
    for ln, i in enumerate(rng.sample(idx_pool, n), start=1):
        price = cat.ITEM_PRICES[i]
        qty = rng.randint(1, 5) if price < Decimal("100") else 1
        net = q2(price * qty)
        lines.append({"line_id": ln, "item_ar": cat.ITEMS[i][0], "item_en": cat.ITEMS[i][1],
                      "qty": qty, "unit_price_sar": price, "net": net, "vat": q2(net * cat.VAT_RATE)})
    return lines


def _build_orders(ds: Dataset, rng: random.Random) -> None:
    cfg = ds.cfg
    dates = cfg.dates
    w = [(1.35 if d >= cfg.ramadan_start else 1.0) * (0.9 if d.weekday() == 4 else 1.0) for d in dates]
    cap_last, _, _ = cfg.last_day_counts
    cap_per_day = allocate(cfg.captures - cap_last, w[:-1]) + [cap_last]
    cash_per_day = allocate(cfg.cash_orders, w)

    slots = [(di, "CARD") for di, n in enumerate(cap_per_day) for _ in range(n)]
    slots += [(di, "CASH") for di, n in enumerate(cash_per_day) for _ in range(n)]
    card_idx = [k for k, s in enumerate(slots) if s[1] == "CARD"]
    rng.shuffle(card_idx)
    n_ecom = int(q2(Decimal(cfg.captures) * cfg.ecom_capture_share))
    ecom_slots = set(card_idx[:n_ecom])  # membership only

    pos_people = [r for r in ds.crm_pos if r["party_type"] == "PERSON" and r["mobile"]]
    org_rows = {r["full_name_en"]: r for r in ds.crm_pos if r["party_type"] == "ORGANIZATION"}
    eco_people = ds.crm_ecom

    for key, (di, means) in enumerate(slots):
        d = dates[di]
        ramadan = d >= cfg.ramadan_start
        if key in ecom_slots:
            channel, store_id, register_id, mid, egs = "ECOM", ECOM_STORE, "", ECOM_MID, ECOM_EGS
        else:
            st = ds.stores[rng.randrange(len(ds.stores))]
            channel, store_id, mid, egs = "POS", st["store_id"], st["merchant_id"], st["egs_id"]
            register_id = rng.choice(st["registers"])
        scheme = None
        if means == "CARD":
            scheme = _weighted(rng, cat.ECOM_SCHEME_MIX if channel == "ECOM" else cat.STORE_SCHEME_MIX)
        flow, cref, bname, bmobile, baddr, org = "REPORTING", "", "", "", "", None
        if channel == "ECOM":
            r = rng.choice(eco_people)
            cref, bname, bmobile, baddr = (r["source_customer_id"], r["full_name_en"] or r["full_name_ar"],
                                           r["mobile"], r["spl_short_address"])
        elif rng.random() < cfg.b2b_share:
            org = ds.orgs[rng.randrange(len(ds.orgs))]
            flow, cref = "CLEARANCE", org_rows[org.name_en]["source_customer_id"]
        elif rng.random() >= cfg.walk_in_share:
            r = rng.choice(pos_people)
            cref, bmobile = r["source_customer_id"], r["mobile"]
        # else: WALK_IN -> empty customer_ref (the NULL skew key of Module 7)
        o = Order(key=key, channel=channel, store_id=store_id, register_id=register_id, merchant_id=mid,
                  egs_id=egs, ts=_pick_ts(rng, d, channel, ramadan),
                  payment_means=scheme if means == "CARD" else "CASH", scheme=scheme, flow=flow,
                  customer_ref=cref, buyer_name=bname, buyer_mobile=bmobile, delivery_addr=baddr,
                  buyer_org=org, lines=_make_lines(rng, channel))
        o.net = sum((ln["net"] for ln in o.lines), ZERO)
        o.vat = sum((ln["vat"] for ln in o.lines), ZERO)
        ds.orders.append(o)

    ds.orders.sort(key=lambda o: (o.ts, o.key))
    for n, o in enumerate(ds.orders, start=1):
        o.order_id = f"ORD-{n:07d}"
        o.invoice_uuid = _uuid(rng)


def _build_payments(ds: Dataset, rng: random.Random) -> None:
    cfg = ds.cfg
    dates = cfg.dates
    w = [(1.35 if d >= cfg.ramadan_start else 1.0) for d in dates]
    _, ref_last, cb_last = cfg.last_day_counts
    ref_per_day = [0] + allocate(cfg.refunds - ref_last, w[1:-1]) + [ref_last]
    cb_per_day = [0, 0, 0] + allocate(cfg.chargebacks - cb_last, w[3:-1]) + [cb_last]

    card_by_day: dict[date, list[Order]] = defaultdict(list)
    for o in ds.orders:
        if o.scheme:
            card_by_day[o.ts.date()].append(o)

    def end_of_day_clamp(ts: datetime, add: int) -> datetime:
        limit = datetime.combine(ts.date(), time(23, 59, 59), tzinfo=KSA)
        return min(ts + timedelta(seconds=add), limit)

    for o in ds.orders:
        if o.scheme:
            ds.payments.append(PaymentEvent("CAPTURE", o, end_of_day_clamp(o.ts, rng.randint(5, 90)), o.total))

    for di, d in enumerate(dates):
        ramadan = d >= cfg.ramadan_start
        for kind, n_today, min_lag, max_lag in (("REFUND", ref_per_day[di], 1, 10),
                                                ("CHARGEBACK", cb_per_day[di], 3, 14)):
            pool = [o for dd in dates[max(0, di - max_lag): max(0, di - min_lag + 1)]
                    for o in card_by_day[dd] if not o.refunded_or_disputed]
            for o in rng.sample(pool, n_today):
                o.refunded_or_disputed = True
                ts = _pick_ts(rng, d, o.channel, ramadan)
                if kind == "REFUND":
                    line = rng.choice(o.lines)
                    unit_net = q2(line["unit_price_sar"])
                    r = Return(order=o, ts=ts, line=line, net=unit_net, vat=q2(unit_net * cat.VAT_RATE),
                               credit_note_uuid=_uuid(rng))
                    ds.returns.append(r)
                    ds.payments.append(PaymentEvent("REFUND", o, end_of_day_clamp(ts, rng.randint(30, 600)),
                                                    r.total, credit_note_uuid=r.credit_note_uuid))
                else:
                    ds.payments.append(PaymentEvent("CHARGEBACK", o, ts, o.total))

    ds.returns.sort(key=lambda r: (r.ts, r.order.order_id))
    for n, r in enumerate(ds.returns, start=1):
        r.return_id = f"RET-{n:06d}"
    ds.payments.sort(key=lambda p: (p.ts, p.order.order_id, p.event_type))
    for n, p in enumerate(ds.payments, start=1):
        p.payment_event_id = f"PE-{n:07d}"


# ----------------------------------------------------------------------------- bank settlement

def bank_fees(scheme: str, event_type: str, gross: Decimal) -> tuple[Decimal, Decimal]:
    """The acquirer's own fee rule (it is the BANK's computation; MIZAN never recomputes real lines)."""
    if event_type == "REFUND":
        fee = ZERO
    elif event_type == "CHARGEBACK":
        fee = cat.CHARGEBACK_FEE
    else:
        rate, cap = cat.FEE_SCHEDULE[scheme]
        fee = q2(gross * rate)
        if cap is not None and fee > cap:
            fee = cap
    return fee, q2(fee * cat.VAT_ON_FEE_RATE)


_BANK_TXN = {"CAPTURE": "PURCHASE", "REFUND": "REFUND", "CHARGEBACK": "CHARGEBACK"}
SETTLEMENT_COLUMNS = ["settlement_batch_id", "payout_date", "merchant_id", "payment_event_id", "txn_type",
                      "card_scheme", "txn_ts_ksa", "settlement_for_date", "gross_amount", "mdr_fee",
                      "vat_on_fee", "net_amount", "dr_cr"]


def settlement_line(p: PaymentEvent, for_date: date) -> dict:
    fee, vat = bank_fees(p.order.scheme, p.event_type, p.amount)
    if p.event_type == "CAPTURE":
        net, drcr = p.amount - fee - vat, "CR"
    else:
        net, drcr = p.amount + fee + vat, "DR"
    payout = for_date + timedelta(days=1)
    return {"settlement_batch_id": f"STL-{payout:%Y%m%d}-NAJDACQ", "payout_date": payout.isoformat(),
            "merchant_id": p.order.merchant_id, "payment_event_id": p.payment_event_id,
            "txn_type": _BANK_TXN[p.event_type], "card_scheme": p.order.scheme,
            "txn_ts_ksa": p.ts.strftime("%Y-%m-%d %H:%M:%S"), "settlement_for_date": for_date.isoformat(),
            "gross_amount": fmt_sar(p.amount), "mdr_fee": fmt_sar(fee), "vat_on_fee": fmt_sar(vat),
            "net_amount": fmt_sar(net), "dr_cr": drcr}


# ----------------------------------------------------------------------------- GL (ACDOCA-shaped)

GL_COLUMNS = ["RLDNR", "RBUKRS", "GJAHR", "BELNR", "DOCLN", "BUDAT", "BLDAT", "RACCT", "DRCRK", "HSL",
              "RHCUR", "PRCTR", "ZZ_STORE_ID", "ZZ_MERCHANT_ID", "SGTXT"]


def _build_gl(ds: Dataset) -> tuple[list[dict], dict]:
    """Daily POS/e-com sales journal per store: one line per (store, day, GL account).

    CARD_CLEARING (net) = captures - refunds - chargebacks of that MID-day, so the GL leg ties to the
    payment leg. HSL is kept positive and DRCRK carries the direction (project money rule)."""
    agg: dict[tuple, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    parts: dict[tuple, list[tuple[str, Decimal]]] = defaultdict(list)  # for the float-bug demo
    for o in ds.orders:
        k = (o.ts.date(), o.store_id, o.merchant_id)
        if o.payment_means == "CASH":
            agg[k]["100100"] += o.total
        agg[k]["400000"] -= o.net
        agg[k]["220100"] -= o.vat
    for r in ds.returns:
        k = (r.ts.date(), r.order.store_id, r.order.merchant_id)
        agg[k]["400000"] += r.net
        agg[k]["220100"] += r.vat
    for p in ds.payments:
        k = (p.ts.date(), p.order.store_id, p.order.merchant_id)
        sign = 1 if p.event_type == "CAPTURE" else -1
        agg[k]["113100"] += sign * p.amount
        parts[k].append((p.event_type, p.amount))
        if p.event_type == "CHARGEBACK":
            agg[k]["680100"] += p.amount
    rows: list[dict] = []
    card_line_ref: dict[tuple, dict] = {}
    for n, k in enumerate(sorted(agg), start=1):
        d, store, mid = k
        belnr = f"{1900000000 + n:010d}"
        docln = 0
        for acct in ("100100", "113100", "400000", "220100", "680100"):
            if acct not in agg[k]:
                continue
            signed = agg[k][acct]  # positive = debit
            if signed == ZERO:
                continue
            docln += 1
            row = {"RLDNR": cat.LEDGER, "RBUKRS": cat.COMPANY_CODE, "GJAHR": str(d.year), "BELNR": belnr,
                   "DOCLN": f"{docln:06d}", "BUDAT": f"{d:%Y%m%d}", "BLDAT": f"{d:%Y%m%d}", "RACCT": acct,
                   "DRCRK": "S" if signed > 0 else "H", "HSL": fmt_sar(abs(signed)), "RHCUR": "SAR",
                   "PRCTR": f"PC-{store}", "ZZ_STORE_ID": store, "ZZ_MERCHANT_ID": mid,
                   "SGTXT": f"Daily sales journal {store} {d.isoformat()}"}
            rows.append(row)
            if acct == "113100":
                card_line_ref[k] = row
        debit = sum((Decimal(r["HSL"]) for r in rows if r["BELNR"] == belnr and r["DRCRK"] == "S"), ZERO)
        credit = sum((Decimal(r["HSL"]) for r in rows if r["BELNR"] == belnr and r["DRCRK"] == "H"), ZERO)
        assert debit == credit, f"unbalanced journal {belnr}"
    # D06: the first card-clearing line where a float sum truncated to 2 dp loses a halala
    float_bug = None
    for k in sorted(card_line_ref):
        row = card_line_ref[k]
        if row["DRCRK"] != "S":
            continue
        f = 0.0
        for et, amt in parts[k]:
            f += float(amt) if et == "CAPTURE" else -float(amt)
        truncated = Decimal(str(math.floor(f * 100) / 100)).quantize(Decimal("0.01"))
        if truncated != Decimal(row["HSL"]):
            float_bug = dict(row, HSL=fmt_sar(truncated))
            break
    return rows, {"float_bug_row": float_bug}


# ----------------------------------------------------------------------------- ZATCA requests + fault plan

def _seller_address() -> dict:
    """BG-5, the seller's postal address: required by EN 16931 rule BR-08 on every invoice."""
    return {"street_ar": cat.SELLER_STREET_AR, "building_number": cat.SELLER_BUILDING_NUMBER,
            "additional_number": cat.SELLER_ADDITIONAL_NUMBER,
            "district_ar": cat.SELLER_DISTRICT_AR, "city_ar": cat.SELLER_CITY_AR,
            "postal_zone": cat.SELLER_POSTAL_ZONE, "region_ar": cat.SELLER_REGION_AR,
            "country_code": cat.SELLER_COUNTRY_CODE}


def _invoice_request(o: Order) -> dict:
    buyer = None
    if o.buyer_org is not None:
        b = o.buyer_org
        buyer = {"name_ar": b.name_ar, "name_en": b.name_en, "vat_number": b.vat_number,
                 "unified_700": b.unified_700, "city": cat.CITIES[b.city_i][1]}
    return {"request_id": "", "invoice_uuid": o.invoice_uuid, "document_type": "INVOICE",
            "invoice_flow": o.flow, "egs_id": o.egs_id, "order_id": o.order_id, "merchant_id": o.merchant_id,
            "store_id": o.store_id, "register_id": o.register_id, "issue_ts_utc": utc_iso(o.ts),
            "customer_ref": o.customer_ref, "buyer": buyer, "payment_means": o.payment_means,
            "billing_reference_uuid": None,
            "seller": {"name": cat.SELLER_NAME, "name_ar": cat.SELLER_NAME_AR, "vat_number": cat.SELLER_VAT,
                       "cr_number": cat.SELLER_CR, "address": _seller_address()},
            "lines": [{"line_id": ln["line_id"], "item_ar": ln["item_ar"], "item_en": ln["item_en"],
                       "qty": ln["qty"], "unit_price_sar": fmt_sar(ln["unit_price_sar"]), "vat_rate": "15.00",
                       "line_net_sar": fmt_sar(ln["net"]), "line_vat_sar": fmt_sar(ln["vat"])}
                      for ln in o.lines],
            "total_excl_vat_sar": fmt_sar(o.net), "vat_total_sar": fmt_sar(o.vat),
            "total_incl_vat_sar": fmt_sar(o.total)}


def _credit_note_request(r: Return) -> dict:
    o, ln = r.order, r.line
    req = _invoice_request(o)
    req.update({"invoice_uuid": r.credit_note_uuid, "document_type": "CREDIT_NOTE",
                "issue_ts_utc": utc_iso(r.ts), "billing_reference_uuid": o.invoice_uuid,
                "return_id": r.return_id,
                "lines": [{"line_id": 1, "item_ar": ln["item_ar"], "item_en": ln["item_en"], "qty": 1,
                           "unit_price_sar": fmt_sar(ln["unit_price_sar"]), "vat_rate": "15.00",
                           "line_net_sar": fmt_sar(r.net), "line_vat_sar": fmt_sar(r.vat)}],
                "total_excl_vat_sar": fmt_sar(r.net), "vat_total_sar": fmt_sar(r.vat),
                "total_incl_vat_sar": fmt_sar(r.total)})
    return req


def _build_requests(ds: Dataset) -> tuple[list[dict], dict]:
    cfg = ds.cfg
    reqs = [_invoice_request(o) for o in ds.orders] + [_credit_note_request(r) for r in ds.returns]
    reqs.sort(key=lambda q: (q["issue_ts_utc"], q["document_type"], q["invoice_uuid"]))
    for n, q in enumerate(reqs, start=1):
        q["request_id"] = f"IR-{n:07d}"
    per_egs: dict[str, list[dict]] = defaultdict(list)
    for q in reqs:
        per_egs[q["egs_id"]].append(q)
    tape = per_egs[cfg.tape_egs]
    p101, p102, p103, p104 = (tape[i - 1] for i in (101, 102, 103, 104))
    assert all(q["invoice_flow"] == "REPORTING" for q in (p101, p102, p103, p104))
    # D04: header VAT total disagrees with the line sum by 0.01 -> mock Fatoora returns HTTP 400
    p103["vat_total_sar"] = fmt_sar(Decimal(p103["vat_total_sar"]) + Decimal("0.01"))
    p103["total_incl_vat_sar"] = fmt_sar(Decimal(p103["total_incl_vat_sar"]) + Decimal("0.01"))
    tamper = per_egs[cfg.tamper_egs][cfg.tamper_icv - 1]
    plan = {
        "default_response": "HTTP_200",
        "responses": {
            p102["request_id"]: ["TRANSPORT_TIMEOUT", "WORKER_CRASH_IN_SUBMITTING", "HTTP_200"],
            p103["request_id"]: ["HTTP_400"],
        },
        "reject_reasons": {p103["request_id"]: "VAT_TOTAL_MISMATCH"},
        "tamper": [{"action": "DELETE_JOURNAL_ROW", "egs_id": cfg.tamper_egs, "icv": cfg.tamper_icv,
                    "request_id": tamper["request_id"]}],
        "tape": {"egs_id": cfg.tape_egs,
                 "positions": {"101": p101["request_id"], "102": p102["request_id"],
                               "103": p103["request_id"], "104": p104["request_id"]}},
    }
    ds.defects += [
        {"id": "D01", "name": "ZATCA_TRANSPORT_TIMEOUT", "module": "M2",
         "description": f"{cfg.tape_egs} request #102: transport failure (5xx/timeout) on the first attempt.",
         "location": {"file": "zatca/fatoora_fault_plan.json", "request_id": p102["request_id"]},
         "expected_handling": "UNKNOWN_OUTCOME, retry identical UUID + bytes, ends REPORTED",
         "invariants": ["I-01", "I-02", "I-03"]},
        {"id": "D02", "name": "ZATCA_ICV_GAP_TAMPER", "module": "M2",
         "description": f"After signing, journal row {cfg.tamper_egs} ICV {cfg.tamper_icv} is deleted.",
         "location": {"file": "zatca/fatoora_fault_plan.json", "egs_id": cfg.tamper_egs,
                      "icv": cfg.tamper_icv},
         "expected_handling": "chain verifier flags ICV gap and PIH break at the next ICV",
         "invariants": ["I-01", "I-02"]},
        {"id": "D03", "name": "ZATCA_WORKER_CRASH_IN_SUBMITTING", "module": "M2",
         "description": f"{cfg.tape_egs} request #102 second attempt: worker dies after persisting SUBMITTING.",
         "location": {"file": "zatca/fatoora_fault_plan.json", "request_id": p102["request_id"]},
         "expected_handling": "restart recovers SUBMITTING -> UNKNOWN_OUTCOME, resend identical bytes",
         "invariants": ["I-03"]},
        {"id": "D04", "name": "ZATCA_HTTP_400_REJECTION", "module": "M2",
         "description": f"{cfg.tape_egs} request #103 header VAT is 0.01 above its line sum.",
         "location": {"file": "zatca/invoice_requests.jsonl", "request_id": p103["request_id"]},
         "expected_handling": "CONFIRMED_REJECTION retained in chain; correction is a new doc, new ICV",
         "invariants": ["I-01", "I-02"]},
    ]
    return reqs, plan


# ----------------------------------------------------------------------------- writers

def _csv_bytes(columns: list[str], rows: list[dict], encoding: str = "utf-8") -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode(encoding)


def _json_bytes(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


CRM_POS_COLUMNS = ["source_customer_id", "party_type", "full_name_ar", "full_name_en", "national_id", "mobile",
                   "landline", "vat_number", "unified_700", "spl_short_address", "city", "created_date"]
CRM_ECOM_COLUMNS = ["source_customer_id", "party_type", "full_name_ar", "full_name_en", "national_id", "mobile",
                    "landline", "email", "spl_short_address", "city", "created_date"]
ADDR_COLUMNS = ["observation_id", "source_system", "source_customer_id", "short_address", "building_number",
                "secondary_number", "district", "city", "postal_code", "observed_date"]
COMMERCE_COLUMNS = ["event_id", "event_type", "order_id", "return_id", "channel", "store_id", "register_id",
                    "merchant_id", "customer_ref", "buyer_name", "buyer_mobile", "delivery_short_address",
                    "payment_means", "amount_sar", "event_ts_utc"]
PAYMENT_COLUMNS = ["payment_event_id", "event_type", "order_id", "invoice_uuid", "credit_note_uuid",
                   "merchant_id", "store_id", "register_id", "payment_scheme", "amount_sar", "currency",
                   "event_ts_utc"]


def generate(out_dir: Path | str, cfg: GenConfig | None = None) -> dict:
    """Generate the full dataset into out_dir. Returns the control manifest (file -> sha256, rows)."""
    cfg = cfg or GenConfig()
    out = Path(out_dir)
    rng = random.Random(cfg.seed)
    ds = Dataset(cfg)
    _build_reference(ds)
    _build_parties(ds, rng)
    _build_crm(ds, rng)
    _build_orders(ds, rng)
    _build_payments(ds, rng)
    reqs, plan = _build_requests(ds)
    gl_rows, gl_extra = _build_gl(ds)

    files: dict[str, tuple[bytes, int, str]] = {}

    def put(rel: str, data: bytes, rows: int, encoding: str = "utf-8") -> None:
        files[rel] = (data, rows, encoding)

    # orders
    ev = []
    for o in ds.orders:
        ev.append({"_ts": o.ts, "_k": (0, o.order_id), "event_type": "ORDER_PLACED", "order_id": o.order_id,
                   "return_id": "", "channel": o.channel, "store_id": o.store_id, "register_id": o.register_id,
                   "merchant_id": o.merchant_id, "customer_ref": o.customer_ref, "buyer_name": o.buyer_name,
                   "buyer_mobile": o.buyer_mobile, "delivery_short_address": o.delivery_addr,
                   "payment_means": o.payment_means, "amount_sar": fmt_sar(o.total), "event_ts_utc": utc_iso(o.ts)})
    for r in ds.returns:
        o = r.order
        ev.append({"_ts": r.ts, "_k": (1, r.return_id), "event_type": "RETURN_REQUESTED", "order_id": o.order_id,
                   "return_id": r.return_id, "channel": o.channel, "store_id": o.store_id,
                   "register_id": o.register_id, "merchant_id": o.merchant_id, "customer_ref": o.customer_ref,
                   "buyer_name": o.buyer_name, "buyer_mobile": o.buyer_mobile,
                   "delivery_short_address": o.delivery_addr, "payment_means": o.payment_means,
                   "amount_sar": fmt_sar(r.total), "event_ts_utc": utc_iso(r.ts)})
    ev.sort(key=lambda e: (e["_ts"], e["_k"]))
    for n, e in enumerate(ev, start=1):
        e["event_id"] = f"CE-{n:07d}"
    put("orders/commerce_events.csv", _csv_bytes(COMMERCE_COLUMNS, ev), len(ev))

    # ZATCA
    put("zatca/invoice_requests.jsonl",
        "".join(json.dumps(q, sort_keys=True, ensure_ascii=False) + "\n" for q in reqs).encode("utf-8"), len(reqs))
    put("zatca/fatoora_fault_plan.json", _json_bytes(plan), 0)

    # payments
    pay_rows = [{"payment_event_id": p.payment_event_id, "event_type": p.event_type, "order_id": p.order.order_id,
                 "invoice_uuid": p.order.invoice_uuid, "credit_note_uuid": p.credit_note_uuid,
                 "merchant_id": p.order.merchant_id, "store_id": p.order.store_id,
                 "register_id": p.order.register_id, "payment_scheme": p.order.scheme,
                 "amount_sar": fmt_sar(p.amount), "currency": "SAR", "event_ts_utc": utc_iso(p.ts)}
                for p in ds.payments]
    put("payments/payment_events.csv", _csv_bytes(PAYMENT_COLUMNS, pay_rows), len(pay_rows))

    # bank settlement: one file per payout date; the last business date's file has not arrived
    last_day = cfg.dates[-1]
    by_payout: dict[date, list[dict]] = defaultdict(list)
    in_transit = []
    for p in ds.payments:
        fd = p.ts.date()
        if fd == last_day:
            in_transit.append(p.payment_event_id)
            continue
        by_payout[fd + timedelta(days=1)].append(settlement_line(p, fd))
    n_settle = 0
    for payout in sorted(by_payout):
        lines = sorted(by_payout[payout], key=lambda r: (r["merchant_id"], r["payment_event_id"]))
        put(f"settlement/NAJDACQ_SETTLEMENT_{payout:%Y%m%d}.csv", _csv_bytes(SETTLEMENT_COLUMNS, lines), len(lines))
        n_settle += len(lines)
    resend_day = cfg.start + timedelta(days=cfg.resend_payout_offset)
    orig = f"settlement/NAJDACQ_SETTLEMENT_{resend_day:%Y%m%d}.csv"
    resend = f"settlement/NAJDACQ_SETTLEMENT_{resend_day:%Y%m%d}_RESEND.csv"
    put(resend, files[orig][0], files[orig][1])

    # demo overlay (kept OUT of the main build; recon circuit-breaker demo flag)
    orphan_src = next(p for p in ds.payments
                      if p.event_type == "CAPTURE" and p.order.scheme == "MADA" and p.order.channel == "POS"
                      and p.ts.date() == cfg.start + timedelta(days=5))
    orphan = settlement_line(orphan_src, orphan_src.ts.date())
    orphan["payment_event_id"] = "PE-9900001"
    put("demo/settlement_demo_orphan.csv", _csv_bytes(SETTLEMENT_COLUMNS, [orphan]), 1)
    fb = gl_extra["float_bug_row"]
    assert fb is not None, "no float-truncation candidate found"
    put("demo/erp_gl_demo_float_bug.csv", _csv_bytes(GL_COLUMNS, [fb]), 1)

    # GL
    put("erp/erp_gl_acdoca.csv", _csv_bytes(GL_COLUMNS, gl_rows), len(gl_rows))

    # CRM
    put("crm/crm_pos_cp1256.csv", _csv_bytes(CRM_POS_COLUMNS, ds.crm_pos, "cp1256"), len(ds.crm_pos), "cp1256")
    put("crm/crm_ecom_utf8.csv", _csv_bytes(CRM_ECOM_COLUMNS, ds.crm_ecom), len(ds.crm_ecom))
    put("crm/spl_address_observations.csv", _csv_bytes(ADDR_COLUMNS, ds.addr_obs), len(ds.addr_obs))

    # reference
    put("reference/merchants.csv", _csv_bytes(
        ["merchant_id", "store_id", "channel", "egs_id", "city", "register_count"],
        [{**s, "register_count": len(s["registers"])} for s in ds.stores]
        + [{"merchant_id": ECOM_MID, "store_id": ECOM_STORE, "channel": "ECOM", "egs_id": ECOM_EGS,
            "city": "Riyadh", "register_count": 0}]), cfg.n_stores + 1)
    put("reference/acquirer_fee_schedule.csv", _csv_bytes(
        ["card_scheme", "mdr_rate", "fee_cap_sar", "chargeback_fee_sar", "vat_on_fee_rate"],
        [{"card_scheme": s, "mdr_rate": str(r), "fee_cap_sar": fmt_sar(c) if c is not None else "",
          "chargeback_fee_sar": fmt_sar(cat.CHARGEBACK_FEE), "vat_on_fee_rate": str(cat.VAT_ON_FEE_RATE)}
         for s, (r, c) in cat.FEE_SCHEDULE.items()]), len(cat.FEE_SCHEDULE))
    put("reference/gl_account_roles.csv", _csv_bytes(
        ["RACCT", "gl_account_role", "normal_side"],
        [{"RACCT": a, "gl_account_role": role, "normal_side": side} for a, (role, side) in cat.GL_ACCOUNTS.items()]),
        len(cat.GL_ACCOUNTS))

    # remaining planted defects
    ecom_events = sum(1 for p in ds.payments if p.order.merchant_id == ECOM_MID)
    walk_in = sum(1 for o in ds.orders if o.channel == "POS" and not o.customer_ref)
    ds.defects += [
        {"id": "D05", "name": "ORPHAN_SETTLEMENT_LINE", "module": "M3",
         "description": "A bank line whose payment_event_id exists in no payment feed (demo overlay).",
         "location": {"file": "demo/settlement_demo_orphan.csv", "payment_event_id": "PE-9900001",
                      "merchant_id": orphan["merchant_id"], "settlement_for_date": orphan["settlement_for_date"]},
         "expected_handling": "key spine keeps it; circuit breaker fails exactly that MID-day when the demo "
                              "flag loads the overlay", "invariants": ["I-05"]},
        {"id": "D06", "name": "FLOAT_HALALA_DRIFT", "module": "M3",
         "description": "ERP card-clearing line computed with a float sum truncated to 2 dp: 0.01 SAR short "
                        "(demo overlay replaces the line with the same BELNR/DOCLN).",
         "location": {"file": "demo/erp_gl_demo_float_bug.csv", "BELNR": fb["BELNR"], "DOCLN": fb["DOCLN"],
                      "merchant_id": fb["ZZ_MERCHANT_ID"], "posting_date": fb["BUDAT"]},
         "expected_handling": "GL variance 0.01 on exactly that MID-day fails the circuit breaker",
         "invariants": ["I-06"]},
        {"id": "D07", "name": "DUPLICATE_SETTLEMENT_BATCH", "module": "M3/M7",
         "description": "The bank re-sends one T+1 settlement file byte-for-byte under a new name.",
         "location": {"file": resend, "duplicate_of": orig},
         "expected_handling": "ctl.applied_event_ledger dedup: replay is idempotent, no double count",
         "invariants": ["I-12"]},
        {"id": "D12", "name": "MEGA_MID_SKEW_AND_WALK_IN", "module": "M7",
         "description": f"E-commerce MID {ECOM_MID} carries {ecom_events} of {len(ds.payments)} payment events; "
                        f"{walk_in} POS orders have no customer (WALK_IN / NULL key).",
         "location": {"merchant_id": ECOM_MID, "ecom_payment_events": ecom_events,
                      "payment_events": len(ds.payments), "walk_in_pos_orders": walk_in},
         "expected_handling": "16-bucket salting + WALK_IN split; salted == unsalted row count and SAR sum",
         "invariants": ["I-11"]},
    ]
    ds.defects.sort(key=lambda d: d["id"])
    manifest = {
        "spec": "MIZAN-KSA v1.1 Design Freeze", "seed": cfg.seed,
        "period_ksa": [cfg.start.isoformat(), cfg.dates[-1].isoformat()],
        "counts": {"commerce_events": len(ev), "invoice_requests": len(reqs), "payment_events": len(pay_rows),
                   "settlement_lines": n_settle, "in_transit_events": len(in_transit),
                   "gl_lines": len(gl_rows),
                   "crm_and_spl_records": len(ds.crm_pos) + len(ds.crm_ecom) + len(ds.addr_obs)},
        "defects": ds.defects,
    }
    manifest["counts"]["total_rows"] = sum(v for k, v in manifest["counts"].items() if k != "in_transit_events")
    put("defect_manifest.json", _json_bytes(manifest), len(ds.defects))

    control = {"seed": cfg.seed, "files": {}}
    for rel in sorted(files):
        data, rows, enc = files[rel]
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        control["files"][rel] = {"sha256": hashlib.sha256(data).hexdigest(), "rows": rows, "encoding": enc,
                                 "bytes": len(data)}
    (out / "_control.json").write_bytes(_json_bytes(control))
    return control
