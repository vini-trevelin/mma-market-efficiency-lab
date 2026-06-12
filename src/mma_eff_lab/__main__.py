from __future__ import annotations

import argparse
import json
from pathlib import Path

from mma_eff_lab.audit.warehouse import validate_warehouse
from mma_eff_lab.download.sherdog import (
    PROMOTION_SETS,
    download_sherdog,
    download_sherdog_ufc_profiles,
    retry_missing_sherdog_fighters,
)
from mma_eff_lab.download.ufcstats import download_ufcstats
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.models.dataset import write_model_dataset
from mma_eff_lab.models.train import train_xgboost_model
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

    sherdog_profiles = subparsers.add_parser("download-sherdog-ufc-profiles")
    sherdog_profiles.add_argument("--limit-fighters", type=int)
    sherdog_profiles.add_argument("--sleep-seconds", type=float, default=1.0)

    subparsers.add_parser("parse-ufcstats")
    subparsers.add_parser("parse-sherdog")
    subparsers.add_parser("build-warehouse")
    subparsers.add_parser("build-features")
    model_dataset = subparsers.add_parser("build-model-dataset")
    model_dataset.add_argument("--output-path")
    train_model = subparsers.add_parser("train-xgboost-model")
    train_model.add_argument("--output-dir")
    train_model.add_argument("--n-estimators", type=int, default=200)
    train_model.add_argument("--max-depth", type=int, default=3)
    train_model.add_argument("--learning-rate", type=float, default=0.05)
    subparsers.add_parser("make-reports")
    subparsers.add_parser("validate-warehouse")
    subparsers.add_parser("apply-identity-overrides")
    subparsers.add_parser("full-pipeline")
    subparsers.add_parser("full-pipeline-sherdog-major")
    subparsers.add_parser("repair-sherdog-major")

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
    elif args.command == "download-sherdog-ufc-profiles":
        result = download_sherdog_ufc_profiles(
            sleep_seconds=args.sleep_seconds,
            limit_fighters=args.limit_fighters,
        )
    elif args.command == "parse-ufcstats":
        result = parse_cached_ufcstats()
    elif args.command == "parse-sherdog":
        result = parse_cached_sherdog()
    elif args.command == "build-warehouse":
        result = build_warehouse()
    elif args.command == "build-features":
        result = build_pit_features()
    elif args.command == "build-model-dataset":
        result = write_model_dataset(Path(args.output_path) if args.output_path else None)
    elif args.command == "train-xgboost-model":
        result = train_xgboost_model(
            output_dir=Path(args.output_dir) if args.output_dir else None,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
        )
    elif args.command == "make-reports":
        result = make_reports()
    elif args.command == "validate-warehouse":
        result = validate_warehouse()
    elif args.command == "apply-identity-overrides":
        result = {
            "warehouse": build_warehouse(),
            "features": build_pit_features(),
            "audit": validate_warehouse(),
        }
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
    elif args.command == "repair-sherdog-major":
        result = {
            "retry_missing_fighters": retry_missing_sherdog_fighters(),
            "parse_sherdog": parse_cached_sherdog(),
            "warehouse": build_warehouse(),
            "features": build_pit_features(),
            "audit": validate_warehouse(),
        }
    else:
        raise SystemExit(f"Unknown command: {args.command}")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
