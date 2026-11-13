"""CLI: .\\.venv\\Scripts\\python.exe -m mizan.generator --out data/generated [--seed N]"""

import argparse
import json

from mizan.generator import DEFAULT_SEED, GenConfig, generate


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the deterministic MIZAN-KSA source dataset.")
    ap.add_argument("--out", default="data/generated")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    control = generate(args.out, GenConfig(seed=args.seed))
    total = sum(f["rows"] for f in control["files"].values())
    print(json.dumps({"out": args.out, "files": len(control["files"]), "rows_incl_resend": total}, indent=2))


if __name__ == "__main__":
    main()
