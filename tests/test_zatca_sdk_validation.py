"""ZATCA's own offline SDK must accept MIZAN's signed invoices.

The SDK is not committed and not downloaded automatically: ZATCA gates it behind an "I accept the terms
and conditions" checkbox and publishes no licence or redistribution terms with it. So this module skips
unless the owner has installed the SDK locally and pointed ZATCA_SDK_HOME at it. CI therefore stays green
on a fresh clone, while the owner can still prove the claim "ZATCA's own tool accepts these invoices".

Install: see scripts/validate_with_zatca_sdk.py
Run:     .\\.venv\\Scripts\\python.exe -m pytest tests/test_zatca_sdk_validation.py -v
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("zatca_sdk", REPO / "scripts" / "validate_with_zatca_sdk.py")
sdk_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sdk_mod)


@pytest.fixture(scope="module")
def sdk():
    found = sdk_mod.find_sdk(None)
    if not found:
        pytest.skip("ZATCA SDK not installed (set ZATCA_SDK_HOME); see scripts/validate_with_zatca_sdk.py")
    cmd = sdk_mod.sdk_command(found)
    if not cmd:
        pytest.skip(f"no SDK launcher or jar under {found}, or no Java runtime on PATH")
    return found, cmd


@pytest.fixture(scope="module")
def invoices(tmp_path_factory, gen_dir):
    out = tmp_path_factory.mktemp("zatca_sdk_xml")
    written = sdk_mod.export_invoices(limit=10, out_dir=out, data_dir=gen_dir)
    assert written, "the clearance engine produced no invoices to validate"
    return written


STAGE = __import__("re").compile(r"\[(XSD|EN|KSA|QR)\] validation result : (\w+)")


def _stages(cmd, xml, home):
    """Run the SDK and return {stage: PASSED|FAILED} plus the error codes it reported."""
    import os
    import subprocess
    proc = subprocess.run([*cmd, "-validate", "-invoice", str(xml)], cwd=home / "Apps",
                          env=sdk_mod.sdk_env(home), capture_output=True, timeout=180,
                          text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    codes = [ln.split("CODE :")[-1].split(",")[0].strip() for ln in out.splitlines() if "CODE :" in ln]
    assert os.path.exists(xml)
    return dict(STAGE.findall(out)), codes


def test_zatca_sdk_passes_xsd_and_en16931(sdk, invoices):
    """ZATCA's own SDK must accept our XML structure and the EN 16931 business rules.

    These are the stages we fully control, so a failure here is a real compliance bug in MIZAN.
    The KSA and QR stages are asserted separately below, because two of their rules cannot be
    satisfied by any invoice (see HONESTY.md).
    """
    home, cmd = sdk
    bad = []
    for label, xml in invoices:
        stages, codes = _stages(cmd, xml, home)
        for stage in ("XSD", "EN"):
            if stages.get(stage) != "PASSED":
                bad.append(f"{label}: {stage} {stages.get(stage)} {codes}")
    assert not bad, "ZATCA's SDK rejected structure or EN 16931 rules:\n  " + "\n  ".join(bad)


def test_zatca_sdk_ksa_failures_are_only_the_known_validator_defects(sdk, invoices):
    """The KSA stage may only ever fail on BR-KSA-50, and only for the validator's float drift.

    BR-KSA-50 asserts line VAT = net x rate/100 with no tolerance, evaluated in IEEE doubles: for a
    line of 96.00 the schematron computes 14.399999999999999 and rejects our exact 14.40. Our money is
    Decimal by design, so this is a defect in the rule, not in MIZAN. Any OTHER KSA code appearing here
    is a genuine bug and must fail this test.
    """
    home, cmd = sdk
    unexpected = []
    for label, xml in invoices:
        stages, codes = _stages(cmd, xml, home)
        if stages.get("KSA") == "PASSED":
            continue
        for code in codes:
            if code.startswith("BR-") and code != "BR-KSA-50":
                unexpected.append(f"{label}: {code}")
    assert not unexpected, "new KSA rule failures (not the known float defect):\n  " + "\n  ".join(unexpected)


def test_exported_invoice_is_well_formed_xml(gen_dir):
    """Runs with or without the SDK: the signed bytes must at least parse and carry the UBL root.

    This is the part of the claim we can always check, so a clone without the SDK still gets a real test.

    Takes `gen_dir` -- the session's freshly generated dataset -- rather than reading `data/generated`, which is
    git-ignored and so never exists on CI. Reading it directly broke every CI run from 2026-11-16, while passing
    on any machine that had run the generator: the failure mode a test that depends on local state always has.
    """
    from xml.etree import ElementTree

    with tempfile.TemporaryDirectory() as tmp:
        written = sdk_mod.export_invoices(limit=3, out_dir=Path(tmp), data_dir=gen_dir)
        assert written, "the clearance engine produced no invoices"
        for label, xml in written:
            root = ElementTree.fromstring(xml.read_bytes())
            assert root.tag.endswith("Invoice"), f"{label}: unexpected root element {root.tag}"
            text = xml.read_bytes()
            assert b"UBLExtensions" in text, f"{label}: signed invoice has no ext:UBLExtensions"
            assert b"AdditionalDocumentReference" in text, f"{label}: no QR/PIH document reference"


def test_zatca_computes_the_same_invoice_hash_as_mizan(sdk, invoices):
    """ZATCA's own SDK and MIZAN must agree on `invoice_hash`, byte for byte.

    This is the single most consequential agreement in the project. `invoice_hash` is not just a
    checksum -- it becomes the NEXT document's PIH whatever ZATCA later answers, so it is the link that
    holds the chain together. Compute it even slightly differently from ZATCA (remove one element too
    many before canonicalising, use C14N 1.1 instead of 1.0, canonicalise after attaching the QR instead
    of before) and every subsequent document in that EGS chain is wrong, with no way to withdraw them.

    No amount of reading the specification proves agreement. Handing the same bytes to ZATCA's jar and
    comparing does.

    Worth stating what this is NOT: ZATCA's SDK 3.0.8 ships **no sample invoices** -- 15 .xsd schemas and
    zero .xml -- so there is nothing of ZATCA's to hash. These are MIZAN's own signed invoices, hashed by
    ZATCA's tool. That is the stronger direction anyway: the chain depends on our bytes, not theirs.
    """
    home, cmd = sdk
    rows = sdk_mod.compare_hashes(cmd, home, invoices[:3])
    assert rows, "no invoices were hashed"
    for label, mine, theirs in rows:
        assert theirs != "(not returned)", (
            f"{label}: the SDK returned no hash -- its log format may have changed, so the parse in "
            f"sdk_hash() needs rechecking before this test can be trusted either way")
        assert mine == theirs, (
            f"{label}: MIZAN and ZATCA disagree on the invoice hash.\n"
            f"  ZATCA {theirs}\n  MIZAN {mine}\n"
            f"Every document after this one in the EGS chain would carry the wrong PIH.")
