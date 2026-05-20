from __future__ import annotations

import argparse
import json

from mma_eff_lab.audit.warehouse import validate_warehouse
from mma_eff_lab.download.sherdog import PROMOTION_SETS, download_sherdog
from mma_eff_lab.download.ufcstats import download_ufcstats
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.reports.static import make_reports
from mma_eff_lab.warehouse.build import build_warehouse, parse_cached_sherdog, parse_cached_ufcstats


def main() -> None:
    parser = argparse.ArgumentParser(prog="mma_eff_lab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download-ufcstats")
    download.add_argument("--force", action="store_true")
    download.add_argument("--limit-events", type=int)
    download.add_argument("--include-future", action="store_true")
    download.add_argument("--sleep-seconds", type=float, default=1.0)

    sherdog = subparsers.add_parser("download-sherdog")
    sherdog.add_argument("--promotion-set", choices=sorted(PROMOTION_SETS), default="major")
    sherdog.add_argument("--force", action="store_true")
    sherdog.add_argument("--limit-events", type=int)
    sherdog.add_argument("--include-future", action="store_true")
    sherdog.add_argument("--sleep-seconds", type=float, default=1.0)

    subparsers.add_parser("parse-ufcstats")
    subparsers.add_parser("parse-sherdog")
    subparsers.add_parser("build-warehouse")
    subparsers.add_parser("build-features")
    subparsers.add_parser("make-reports")
    subparsers.add_parser("validate-warehouse")
    subparsers.add_parser("full-pipeline")
    subparsers.add_parser("full-pipeline-sherdog-major")

    args = parser.parse_args()
    if args.command == "download-ufcstats":
        result = download_ufcstats(
            force=args.force,
            limit_events=args.limit_events,
            include_future=args.include_future,
            sleep_seconds=args.sleep_seconds,
        )
    elif args.command == "download-sherdog":
        result = download_sherdog(
            promotion_set=args.promotion_set,
            force=args.force,
            limit_events=args.limit_events,
            include_future=args.include_future,
            sleep_seconds=args.sleep_seconds,
        )
    elif args.command == "parse-ufcstats":
        result = parse_cached_ufcstats()
    elif args.command == "parse-sherdog":
        result = parse_cached_sherdog()
    elif args.command == "build-warehouse":
        result = build_warehouse()
    elif args.command == "build-features":
        result = build_pit_features()
    elif args.command == "make-reports":
        result = make_reports()
    elif args.command == "validate-warehouse":
        result = validate_warehouse()
    elif args.command == "full-pipeline":
        result = {
            "download": download_ufcstats(),
            "parse": parse_cached_ufcstats(),
            "warehouse": build_warehouse(),
            "features": build_pit_features(),
            "audit": validate_warehouse(),
            "reports": make_reports(),
        }
    elif args.command == "full-pipeline-sherdog-major":
        result = {
            "download": download_sherdog(promotion_set="major"),
            "parse_ufcstats": parse_cached_ufcstats(),
            "parse_sherdog": parse_cached_sherdog(),
            "warehouse": build_warehouse(),
            "features": build_pit_features(),
            "audit": validate_warehouse(),
            "reports": make_reports(),
        }
    else:
        raise SystemExit(f"Unknown command: {args.command}")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
