"""Rewrite non-ASCII characters in .py files as backslash-u escapes (CLAUDE.md rule).

Usage: .venv/Scripts/python.exe scripts/escape_non_ascii.py src tests
Only safe for characters inside string literals, which is the only place Arabic may appear.
"""
import pathlib
import sys

BS = chr(92)


def esc(c: str) -> str:
    o = ord(c)
    if o < 128:
        return c
    return f"{BS}u{o:04X}" if o < 0x10000 else f"{BS}U{o:08X}"


for root in sys.argv[1:]:
    for p in pathlib.Path(root).rglob("*.py"):
        s = p.read_text(encoding="utf-8")
        if any(ord(c) > 127 for c in s):
            p.write_text("".join(esc(c) for c in s), encoding="utf-8", newline="\n")
            print("escaped", p)
