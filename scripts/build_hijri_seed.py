"""Build dbt/seeds/umm_al_qura_calendar.csv (one row per Gregorian day) from the Umm al-Qura calendar shipped with
Windows (.NET System.Globalization.UmAlQuraCalendar, Microsoft's implementation of the official KACST table).

Run once on Windows; the CSV is committed, so CI and Fabric never need .NET. The output is deterministic.
    .\\.venv\\Scripts\\python.exe scripts\\build_hijri_seed.py
"""

import subprocess
from pathlib import Path

START, END = "2024-12-01", "2028-01-31"
VERSION = "UAQ_DOTNET_V1"
OUT = Path(__file__).resolve().parents[1] / "dbt" / "seeds" / "umm_al_qura_calendar.csv"

PS = f"""
$c = New-Object System.Globalization.UmAlQuraCalendar
$d = [datetime]::ParseExact('{START}','yyyy-MM-dd',$null)
$e = [datetime]::ParseExact('{END}','yyyy-MM-dd',$null)
while ($d -le $e) {{
  '{{0}},{{1}},{{2}},{{3}}' -f $d.ToString('yyyy-MM-dd'), $c.GetYear($d), $c.GetMonth($d), $c.GetDayOfMonth($d)
  $d = $d.AddDays(1)
}}
"""


def main() -> None:
    out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS],
                         capture_output=True, text=True, check=True).stdout
    rows = [line.strip() for line in out.splitlines() if line.strip()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="ascii", newline="\n") as f:
        f.write("calendar_date,hijri_year,hijri_month,hijri_day,calendar_version\n")
        for r in rows:
            f.write(f"{r},{VERSION}\n")
    print(f"{OUT} rows={len(rows)}")


if __name__ == "__main__":
    main()
