"""Create local DEV keys in the git-ignored .env (only adds keys that are missing; never prints them).

Usage: .venv/Scripts/python.exe scripts/init_local_env.py
"""
import base64
import secrets
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
WANTED = ("MIZAN_HMAC_KEY_B64", "MIZAN_KEK_B64", "AIRFLOW_ADMIN_PASSWORD")

existing = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
present = {line.split("=", 1)[0].strip() for line in existing.splitlines() if "=" in line}
added = []
with ENV.open("a", encoding="utf-8", newline="\n") as f:
    if existing and not existing.endswith("\n"):
        f.write("\n")
    for k in WANTED:
        if k not in present:
            f.write(f"{k}={base64.b64encode(secrets.token_bytes(32)).decode()}\n")
            added.append(k)
print(f"{ENV.name}: added {added or 'nothing'} (values not shown)")
