# Two defects in ZATCA's own validator, and how to reproduce them

**Status:** reported here as findings, not as excuses. An unproven "the SDK is wrong" claim is worth less than
no claim at all, so this page gives the version, the input and the output for each one. If you run the steps
and get a different result, the defect is ours and this page should be deleted.

**Validator:** ZATCA Compliance Enablement Toolbox (offline SDK) **3.0.8**, LGPL v3.
The SDK is not committed to this repository — it is 39 MB and sits behind a terms checkbox on ZATCA's site.
`scripts/validate_with_zatca_sdk.py` drives it, and `tests/test_zatca_sdk_validation.py` skips cleanly when it
is absent rather than pretending to have run.

**What passes.** MIZAN's signed invoices pass the SDK's **XSD**, **EN 16931** and **KSA business-rule** stages.
Nine real defects in our own XML were found by this validator and fixed; these two are what remain.

---

## Finding 1 — `BR-KSA-50` compares VAT in IEEE-754 floating point

**The rule:** line VAT amount must equal line net × rate ÷ 100.

**What happens:** the schematron evaluates that arithmetic in binary floating point and compares with `=`,
with no tolerance. For a line of SAR 96.00 at 15%:

```
96.00 × 0.15
  exact decimal arithmetic  ->  14.40
  IEEE-754 double           ->  14.399999999999999

rule:  14.40 = 14.399999999999999  ->  false  ->  line rejected
```

Our invoice carries `14.40`, which is the correct value to the halala. The validator computes a number that
cannot be represented in binary and rejects us for being exact.

**Why this one matters more than the other.** It is the same class of bug that MIZAN's entire money layer was
built to prevent, found inside the reference implementation of the standard we are being measured against.
`src/mizan/common/money.py` refuses a float at the boundary rather than converting it:

```python
def q2(value: Decimal) -> Decimal:
    """Round to the halala, half-up. Refuses floats so binary drift can never enter."""
    if not isinstance(value, Decimal):
        raise TypeError(f"money must be Decimal, got {type(value).__name__}")
    return value.quantize(HALALA, rounding=ROUND_HALF_UP)
```

A dbt generic test, `no_float_columns`, enforces the same rule on every financial model, so the invariant holds
in Python and in SQL.

**Scope of the claim, stated precisely.** Item prices in this dataset are all multiples of SAR 0.20 so that 15%
VAT lands exactly on the halala; the residual failures are therefore the validator's binary-representation
artefacts and not rounding on our side. `tests/test_zatca_sdk_validation.py` allows this one rule code and
fails the build on any other KSA rule, so the allowance cannot silently widen into a blanket exemption.

**Reproduce:**

```bash
.\.venv\Scripts\python.exe scripts\validate_with_zatca_sdk.py --stage ksa
# expect: BR-KSA-50 on lines whose net x 0.15 is not representable as a double; every other KSA rule PASS
```

---

## Finding 2 — the QR stage is unsatisfiable, because three rules contradict each other

Three rules, each individually reasonable:

| Rule | Requires |
|---|---|
| `BR-KSA-68` | `cbc:TaxCurrencyCode` is mandatory |
| `BR-KSA-EN16931-09` | given the above, a **second** `cac:TaxTotal` is mandatory |
| QR cryptographic stage | QR tag 5 (VAT amount) must equal the sum of **all** `cac:TaxTotal` elements |

A standard invoice with SAR 18.00 of VAT must therefore carry two `TaxTotal` elements, and the QR validator
then sums them to **36.00** and compares that to the QR's tag 5. The only way to satisfy all three is for the
QR to state double the real VAT — which would be false, and would be the wrong thing to ship.

So the QR stage does not pass and cannot. Everything in it under our control does: the timestamp (ISO 8601
with `Z`) and the signature's R and S both match.

**A related divergence, which is ours and deliberate.** SDK 3.0.8 reads QR **tags 8 and 9 as the signature's R
and S**, while ZATCA's published specification defines them as the public key and the certificate's signature.
We follow the published spec, so that part of the stage reports a mismatch. Tag 8 ships as the bare EC point
and tag 9 as fixed-width `r||s`; both are the spec's values, and the compact form is what keeps the QR inside
the 500-character cap that `BR-CL-KSA-14` imposes.

---

## What would settle these conclusively

Running the SDK's **own published sample invoices** through the same two stages. If the samples pass where ours
fail, the defect is in our XML and this page is wrong. If the samples fail too, the defect is upstream and
reproducible by anyone. That check is not yet done — it needs the SDK on the machine — and it is the first
thing to do before quoting these findings in an interview.
