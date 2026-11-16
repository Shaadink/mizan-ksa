r"""Assemble the public snapshot site from the standalone Command Center page.

Why a separate site
-------------------
The live Command Center is a Fabric App inside a college tenant: a recruiter without a tenant login
sees a sign-in wall. This site is the same page running on the exported Gold snapshot, hosted publicly
so anyone with the link can open it. It is read-only: no live DAX, no Azure OpenAI agent (Ask MIZAN
replays the recorded, number-verified runs instead).

What it refuses to publish
--------------------------
Before writing anything it scans the page for things that must not go public: e-mail addresses, the
Azure Function endpoint, tenant/workspace identifiers. Any hit aborts the build.

Run
---
    .\.venv\Scripts\python.exe scripts\build_public_site.py
    -> public_site\  (index.html, HONESTY.md, PROOF_MANIFEST.md, robots.txt, staticwebapp.config.json)
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "command_center" / "index.html"
OUT = REPO / "public_site"

# Anything matching these must never reach a public host.
FORBIDDEN: list[tuple[str, str]] = [
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "an e-mail address"),
    (r"func-mizan-agent-[a-z0-9]+", "the Azure Function endpoint"),
    (r"[a-z0-9-]+\.onmicrosoft\.com", "a tenant domain"),
    (r"mizan-admin", "the admin account name"),
    (r"AZURE_[A-Z_]*KEY|api[_-]?key\s*[:=]\s*['\"][^'\"]{12,}", "something that looks like a secret"),
]


def scan(html: str) -> list[str]:
    hits = []
    for pattern, what in FORBIDDEN:
        found = sorted(set(re.findall(pattern, html, re.I)))
        if found:
            hits.append(f"{what}: {', '.join(found[:4])}")
    return hits


def main() -> int:
    if not SRC.exists():
        print(f"{SRC} not found. Run scripts/build_command_center.py first.")
        return 2
    html = SRC.read_text(encoding="utf-8")

    problems = scan(html)
    if problems:
        print("Refusing to build the public site; the page contains:")
        for p in problems:
            print(f"  - {p}")
        return 1

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    (OUT / "index.html").write_text(html, encoding="utf-8", newline="\n")
    for name, src in (("HONESTY.md", REPO / "HONESTY.md"),
                      ("PROOF_MANIFEST.md", REPO / "docs" / "PROOF_MANIFEST.md")):
        if src.exists():
            (OUT / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

    photo = REPO / "apps" / "command-center" / "public" / "profile.jpg"
    if photo.exists():
        shutil.copy2(photo, OUT / "profile.jpg")

    # The badge in the footer links to docs/PROOF_MANIFEST.md; flatten that for this site.
    idx = (OUT / "index.html").read_text(encoding="utf-8")
    idx = idx.replace('href="docs/PROOF_MANIFEST.md"', 'href="PROOF_MANIFEST.md"')
    (OUT / "index.html").write_text(idx, encoding="utf-8", newline="\n")

    (OUT / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8", newline="\n")
    (OUT / "staticwebapp.config.json").write_text(
        '{\n'
        '  "navigationFallback": { "rewrite": "/index.html" },\n'
        '  "mimeTypes": { ".md": "text/plain; charset=utf-8" },\n'
        '  "globalHeaders": {\n'
        '    "X-Content-Type-Options": "nosniff",\n'
        '    "Referrer-Policy": "strict-origin-when-cross-origin"\n'
        '  }\n'
        '}\n', encoding="utf-8", newline="\n")

    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"{OUT.relative_to(REPO)}  ({len(list(OUT.rglob('*')))} files, {total / 1024:.0f} KB)")
    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
