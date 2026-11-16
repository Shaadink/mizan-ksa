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
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
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


def export_invoices(limit: int, out_dir: Path) -> list[tuple[str, Path]]:
    """Re-run the clearance engine and write each signed invoice's XML to out_dir. Returns (label, path)."""
    from mizan.clearance.engine import process_requests
    from mizan.clearance.mock_fatoora import MockFatoora

    data = REPO / "data" / "generated"
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sdk", help=r"path to the unzipped ZATCA SDK (default: $ZATCA_SDK_HOME or vendor\zatca-sdk)")
    ap.add_argument("--limit", type=int, default=20, help="how many invoices to validate (default 20)")
    ap.add_argument("--keep", action="store_true", help="keep the exported XML instead of deleting it")
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
        print(f"Validating {len(invoices)} signed invoices with the ZATCA SDK at {sdk}\n")
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
