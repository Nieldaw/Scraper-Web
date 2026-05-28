from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wrapper pratique: collecte Homegate vente par canton via collect_sale_by_canton.py.",
    )
    parser.add_argument("--canton", help="Canton cible (GE|VD|NE|JU|FR|VS).")
    parser.add_argument("--all-romandie", action="store_true", help="Traiter GE, VD, NE, JU, FR, VS.")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-listings", type=int, default=None)
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--cache-max-age-hours", type=int, default=24)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--retries", type=int, default=None)
    parser.add_argument("--list-config", action="store_true")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    script = Path(__file__).resolve().parent / "collect_sale_by_canton.py"
    cmd = [sys.executable, str(script), "--sources", "homegate", "--max-pages", str(args.max_pages)]

    if args.canton:
        cmd.extend(["--canton", args.canton])
    if args.all_romandie:
        cmd.append("--all-romandie")
    if args.max_listings is not None:
        cmd.extend(["--max-listings", str(args.max_listings)])
    if args.use_cache:
        cmd.append("--use-cache")
    if args.cache_max_age_hours is not None:
        cmd.extend(["--cache-max-age-hours", str(args.cache_max_age_hours)])
    if args.delay_seconds is not None:
        cmd.extend(["--delay-seconds", str(args.delay_seconds)])
    if args.no_export:
        cmd.append("--no-export")
    if args.timeout is not None:
        cmd.extend(["--timeout", str(args.timeout)])
    if args.retries is not None:
        cmd.extend(["--retries", str(args.retries)])
    if args.list_config:
        cmd.append("--list-config")

    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
