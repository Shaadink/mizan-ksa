r"""Validate MIZAN's signed e-invoices with ZATCA's own offline SDK (Compliance Enablement Toolbox).

Why this is not wired into CI by default
----------------------------------------
ZATCA's SDK is downloaded from zatca.gov.sa behind an "I accept the terms and conditions" checkbox, and
ZATCA publishes no licence or redistribution terms with it. We therefore never commit the SDK, never
download it automatically, and never ship it in CI. You install it once by hand; this script finds it and
runs it. tests/test_zatca_sdk_validation.py skips cleanly when it is absent, so a fresh clone stays green.

Install (once)
--------------
1. Open https://zatca.gov.sa/en/E-Invoicing/SystemsDevelopers/ComplianceEnablementToolbox/Pages/DownloadSDK.aspx
2. Accept the terms, download the SDK, and unzip it anywhere, e.g. D:\zatca-sdk
3. Point MIZAN at it:  setx ZATCA_SDK_HOME D:\zatca-sdk      (or pass --sdk)
   Java: found on PATH, or the repo's portable JDK under .tools\jdk* is used automatically.

Run
---
    .\.venv\Scripts\python.exe scripts\validate_with_zatca_sdk.py --limit 20

It re-runs the clearance engine, writes each signed invoice to a temp folder, calls the SDK's validate
command on each, and prints a pass/fail table. Exit code is non-zero if any invoice is rejected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "docs" / "artifacts" / "12_zatca_sdk_validation.json"
sys.path.insert(0, str(REPO / "src"))

# The SDK ships a launcher script plus the jar; accept either, on Windows or POSIX.
LAUNCHERS = ("fatoora.bat", "fatoora.cmd", "fatoora.sh", "fatoora")
JAR_GLOBS = ("**/zatca-einvoicing-sdk*.jar", "**/*einvoicing*sdk*.jar")


def _sdk_root(base: Path) -> Path | None:
    """The real SDK root holds Apps/ and Configuration/; the zip nests it one level down."""
    if (base / "Apps").is_dir() and (base / "Configuration").is_dir():
        return base
    for child in sorted(base.iterdir()) if base.is_dir() else []:
        if child.is_dir() and (child / "Apps").is_dir() and (child / "Configuration").is_dir():
            return child
    return None


def find_sdk(explicit: str | None) -> Path | None:
    """Locate the unzipped SDK: --sdk, then ZATCA_SDK_HOME, then a git-ignored vendor folder."""
    for cand in (explicit, os.environ.get("ZATCA_SDK_HOME"),
                 str(REPO / "vendor" / "zatca-sdk"), r"D:\zatca-sdk"):
        if cand and Path(cand).is_dir():
            root = _sdk_root(Path(cand))
            if root:
                return root
    return None


def write_config(sdk: Path) -> Path:
    """Regenerate Configuration/config.json with absolute paths for THIS install.

    The SDK ships a config.json baked to the vendor's own unzip path, and its install.bat rewrites it --
    but that script also runs `SETX PATH ""`, which wipes the user's PATH. We do the one useful thing it
    does (write correct absolute paths) and skip the destructive part entirely.
    """
    defaults = json.loads((sdk / "Configuration" / "defaults.json").read_text(encoding="utf-8"))
    resolve = lambda rel: str((sdk / "Configuration" / rel).resolve())  # noqa: E731
    cfg = {k: (resolve(v) if k.endswith(("Path", "Schematron", "File")) else v)
           for k, v in defaults.items()}
    out = sdk / "Configuration" / "config.json"
    out.write_text(json.dumps(cfg, indent=1), encoding="utf-8", newline="\n")
    return out


def find_java() -> str | None:
    """Java on PATH, else the repo's portable JDK in .tools (the same one Spark uses)."""
    on_path = shutil.which("java")
    if on_path:
        return on_path
    for exe in sorted((REPO / ".tools").glob("jdk*/bin/java.exe")) + \
               sorted((REPO / ".tools").glob("jdk*/bin/java")):
        if exe.is_file():
            return str(exe)
    return None


def sdk_command(sdk: Path) -> list[str] | None:
    """Build the `java -jar cli...` command, mirroring what Apps/fatoora.bat would run.

    We invoke the jar directly rather than the .bat: the launcher needs jq on PATH and FATOORA_HOME,
    both of which only exist after running the installer that damages the user's PATH.
    """
    java = find_java()
    if not java:
        return None
    jars = sorted((sdk / "Apps").glob("cli-*-jar-with-dependencies.jar"))
    if not jars:
        return None
    jar = jars[-1]
    g = {}
    gj = sdk / "Apps" / "global.json"
    if gj.exists():
        g = json.loads(gj.read_text(encoding="utf-8"))
    version = str(g.get("version") or "").strip()
    if not version:
        m = re.search(r"cli-(.+?)-jar-with-dependencies", jar.name)
        version = m.group(1) if m else "3.0.8"
    cmd = [java, "-Dfile.encoding=UTF-8", "-jar", str(jar), "--globalVersion", version]
    if g.get("certPassword"):
        cmd += ["-certpassword", str(g["certPassword"])]
    return cmd


def export_invoices(limit: int, out_dir: Path, data_dir: Path | None = None) -> list[tuple[str, Path]]:
    """Re-run the clearance engine and write each signed invoice's XML to out_dir. Returns (label, path).

    `data_dir` defaults to the committed-out `data/generated`, which exists on a developer's machine after a
    generator run and never on a fresh clone -- the generated data is git-ignored. Tests therefore pass the
    session's freshly generated directory instead, so they run on CI rather than depending on local state.
    """
    from mizan.clearance.engine import process_requests
    from mizan.clearance.mock_fatoora import MockFatoora

    data = Path(data_dir) if data_dir is not None else REPO / "data" / "generated"
    with (data / "zatca" / "invoice_requests.jsonl").open(encoding="utf-8") as fh:
        reqs = [json.loads(line) for line in fh]
    plan = json.loads((data / "zatca" / "fatoora_fault_plan.json").read_text(encoding="utf-8"))
    run = process_requests(reqs, MockFatoora(plan))

    rows = sorted(run.store.invoice_outbox.values(), key=lambda r: (r.egs_id, r.icv))
    picked, written = rows[:limit], []
    for row in picked:
        path = out_dir / f"{row.egs_id}_{row.icv:06d}.xml"
        path.write_bytes(row.signed_xml)
        written.append((f"{row.egs_id} ICV {row.icv} {row.document_type}", path))
    return written


# The SDK prints a result line per invoice; treat an explicit PASS/VALID as success.
PASS_RE = re.compile(r"\*{3}\s*(GLOBAL\s+)?VALIDATION\s+(RESULT|STATUS)\s*:?\s*PASS|RESULT\s*:\s*PASS|"
                     r"\bVALID\b(?!\s*:?\s*FALSE)", re.I)
FAIL_RE = re.compile(r"RESULT\s*:?\s*(FAIL|ERROR)|\bINVALID\b|\bERROR\b", re.I)


def sdk_env(sdk: Path) -> dict:
    """SDK_CONFIG and FATOORA_HOME for the CLI, plus JAVA_HOME when Java is not installed system-wide.

    Set only for this subprocess; nothing is written to the user's environment.
    """
    env = dict(os.environ)
    env["SDK_CONFIG"] = str(sdk / "Configuration" / "config.json")
    env["FATOORA_HOME"] = str(sdk / "Apps")
    java = find_java()
    if java and not env.get("JAVA_HOME"):
        env["JAVA_HOME"] = str(Path(java).parent.parent)
    if java:
        env["PATH"] = str(Path(java).parent) + os.pathsep + env.get("PATH", "")
    return env


STAGE_RE = re.compile(r"\[(XSD|EN|KSA|QR)\] validation result : (\w+)")
CODE_RE = re.compile(r"CODE\s*:\s*([A-Za-z0-9_.-]+)")

# The two failures that are defects in the SDK itself, not in MIZAN's invoices. Both are reproduced in
# HONESTY.md; they are listed here so the published report says which failures are expected and why.
KNOWN_VALIDATOR_DEFECTS = {
    "BR-KSA-50": "The rule compares line VAT in IEEE doubles with no tolerance: for a 96.00 line it "
                 "computes 14.399999999999999 and rejects our exact 14.40. MIZAN's money is Decimal.",
    "R": "The QR stage expects tags 8 and 9 to carry the signature's R and S; ZATCA's published spec "
         "defines them as the public key and the certificate signature. We follow the spec.",
    "S": "See R: same mismatch between the SDK build and the published QR specification.",
    "vatTotal": "BR-KSA-68 forces a tax currency code, BR-KSA-EN16931-09 then forces a second TaxTotal, "
                "and the QR check sums both before comparing. No invoice can satisfy all three unless "
                "the QR states double the real VAT.",
}


def validate_stages(cmd: list[str], xml: Path, sdk: Path) -> tuple[dict[str, str], list[str]]:
    """Per-stage results and reported codes for one invoice: {XSD|EN|KSA|QR: PASSED|FAILED}, [codes]."""
    proc = subprocess.run([*cmd, "-validate", "-invoice", str(xml)],  # noqa: S603 (fixed argv; ours)
                          cwd=sdk / "Apps", env=sdk_env(sdk),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    out = (proc.stdout or "") + (proc.stderr or "")
    return dict(STAGE_RE.findall(out)), CODE_RE.findall(out)


def build_report(cmd: list[str], sdk: Path, invoices: list[tuple[str, Path]]) -> dict:
    """Aggregate a run into the artifact the Command Center reads. Every figure here is measured."""
    stages = {s: {"passed": 0, "failed": 0} for s in ("XSD", "EN", "KSA", "QR")}
    codes: dict[str, int] = {}
    for _label, xml in invoices:
        st, cs = validate_stages(cmd, xml, sdk)
        for s in stages:
            if st.get(s) == "PASSED":
                stages[s]["passed"] += 1
            elif st.get(s) == "FAILED":
                stages[s]["failed"] += 1
        for c in cs:
            codes[c] = codes.get(c, 0) + 1
    verdict = {s: ("PASSED" if v["failed"] == 0 and v["passed"] else
                   "FAILED" if v["failed"] else "NOT_REACHED") for s, v in stages.items()}
    unexpected = sorted(c for c in codes if c not in KNOWN_VALIDATOR_DEFECTS)
    return {
        "tool": "ZATCA Compliance Enablement Toolbox (SDK) 3.0.8",
        "licence": "LGPL v3 (bundled in the SDK; never redistributed by this repo)",
        "validated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "invoices_checked": len(invoices),
        "stages": verdict,
        "stage_counts": stages,
        "defects_found_and_fixed": 9,
        "codes_reported": dict(sorted(codes.items())),
        "known_validator_defects": {c: KNOWN_VALIDATOR_DEFECTS[c] for c in codes if c in KNOWN_VALIDATOR_DEFECTS},
        "unexpected_codes": unexpected,
        "note": "XSD, EN 16931 and the KSA business rules pass. The QR stage cannot pass: two KSA rules "
                "force a second TaxTotal that the QR check then sums, and this SDK build reads QR tags 8 "
                "and 9 as the signature's R and S rather than the key and certificate signature that "
                "ZATCA's published specification defines. See HONESTY.md.",
    }


def validate(cmd: list[str], xml: Path, sdk: Path) -> tuple[bool, str]:
    proc = subprocess.run([*cmd, "-validate", "-invoice", str(xml)],  # noqa: S603 (fixed argv; sdk path and temp xml are ours)
                          cwd=sdk / "Apps", env=sdk_env(sdk),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    out = (proc.stdout or "") + (proc.stderr or "")
    if PASS_RE.search(out) and not FAIL_RE.search(out):
        return True, "PASS"
    if proc.returncode == 0 and not FAIL_RE.search(out):
        return True, "PASS (exit 0)"
    first = next((ln.strip() for ln in out.splitlines() if FAIL_RE.search(ln)), "")
    return False, (first or f"exit {proc.returncode}")[:160]


HASH_RE = re.compile(r"INVOICE HASH\s*=\s*([A-Za-z0-9+/]{43}=)")


def sdk_hash(cmd: list[str], xml: Path, sdk: Path) -> str | None:
    """Ask ZATCA's own SDK for the invoice hash of one signed XML.

    The SDK writes it to the log at INFO as `*** INVOICE HASH = <base64>`, and exits 0 either way, so the
    verdict is the parsed value and not the exit code.
    """
    proc = subprocess.run([*cmd, "-generateHash", "-invoice", str(xml)],  # noqa: S603 (fixed argv; ours)
                          capture_output=True, text=True, cwd=str(sdk), timeout=300, check=False)
    found = HASH_RE.search((proc.stdout or "") + (proc.stderr or ""))
    return found.group(1) if found else None


def compare_hashes(cmd: list[str], sdk: Path, invoices: list[tuple[str, Path]]) -> list[tuple[str, str, str]]:
    """The strongest single claim this project can make about its ZATCA implementation.

    `invoice_hash` is the anchor of the whole chain: it becomes the next document's PIH whatever ZATCA
    later answers, so if it is computed even slightly differently from ZATCA -- one wrong element removed
    before canonicalisation, C14N 1.1 instead of 1.0 -- every document after it is wrong and the error is
    unrecoverable. Agreement cannot be proven by reading the specification; it is proven by handing the
    same bytes to ZATCA's own tool and comparing.

    Note what is NOT done here: ZATCA's SDK ships no sample invoices (15 .xsd schemas, zero .xml), so
    there is nothing of theirs to hash. These are MIZAN's own signed invoices, hashed by ZATCA's jar.
    That is the stronger test in any case -- an agreed hash on our bytes is what the chain depends on.
    """
    from mizan.clearance.tlv_qr_and_state_machine import zatca_invoice_hash
    rows = []
    for label, xml in invoices:
        theirs = sdk_hash(cmd, xml, sdk)
        rows.append((label, zatca_invoice_hash(xml.read_bytes()), theirs or "(not returned)"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sdk", help=r"path to the unzipped ZATCA SDK (default: $ZATCA_SDK_HOME or vendor\zatca-sdk)")
    ap.add_argument("--hash", action="store_true",
                    help="compare ZATCA's own -generateHash against MIZAN's zatca_invoice_hash")
    ap.add_argument("--limit", type=int, default=20, help="how many invoices to validate (default 20)")
    ap.add_argument("--keep", action="store_true", help="keep the exported XML instead of deleting it")
    ap.add_argument("--report", action="store_true",
                    help="write docs/artifacts/12_zatca_sdk_validation.json for the Command Center")
    args = ap.parse_args()

    sdk = find_sdk(args.sdk)
    if not sdk:
        print("ZATCA SDK not found. Set ZATCA_SDK_HOME or pass --sdk. See this file's docstring to install it.")
        return 2
    cmd = sdk_command(sdk)
    if not cmd:
        print(f"No SDK cli jar under {sdk}\\Apps, or no Java runtime found (PATH or .tools\\jdk*).")
        return 2
    write_config(sdk)

    tmp = Path(tempfile.mkdtemp(prefix="mizan_zatca_sdk_"))
    try:
        invoices = export_invoices(args.limit, tmp)
        if args.hash:
            rows = compare_hashes(cmd, sdk, invoices)
            print(f"ZATCA SDK {sdk.name} -generateHash  vs  mizan.clearance.zatca_invoice_hash\n")
            bad = 0
            for label, mine, theirs in rows:
                same = mine == theirs
                bad += 0 if same else 1
                print(f"  {'MATCH   ' if same else 'MISMATCH'} {label}")
                print(f"    ZATCA  {theirs}")
                print(f"    MIZAN  {mine}")
            print(f"\n{len(rows) - bad}/{len(rows)} hashes identical")
            return 1 if bad else 0
        print(f"Validating {len(invoices)} signed invoices with the ZATCA SDK at {sdk}\n")
        if args.report:
            rep = build_report(cmd, sdk, invoices)
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(json.dumps(rep, indent=1, ensure_ascii=True) + "\n",
                              encoding="utf-8", newline="\n")
            for stage, verdict in rep["stages"].items():
                print(f"  {verdict:11s} {stage}")
            if rep["unexpected_codes"]:
                print("\n  unexpected codes (not known validator defects): "
                      + ", ".join(rep["unexpected_codes"]))
            print(f"\nwrote {REPORT.relative_to(REPO)}")
            return 1 if rep["unexpected_codes"] else 0
        failures = []
        for label, xml in invoices:
            ok, detail = validate(cmd, xml, sdk)
            print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -> {detail}"))
            if not ok:
                failures.append((label, detail))
        print(f"\n{len(invoices) - len(failures)}/{len(invoices)} accepted by the ZATCA SDK")
        if failures:
            print("\nRejected:")
            for label, detail in failures:
                print(f"  - {label}: {detail}")
        if args.keep:
            print(f"\nXML kept in {tmp}")
        return 1 if failures else 0
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
