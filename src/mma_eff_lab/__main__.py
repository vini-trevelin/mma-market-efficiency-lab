from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from mma_eff_lab.audit.warehouse import validate_warehouse
from mma_eff_lab.download.sherdog import (
    PROMOTION_SETS,
    download_sherdog,
    download_sherdog_ufc_profiles,
    retry_missing_sherdog_fighters,
)
from mma_eff_lab.download.ufcstats import download_ufcstats
from mma_eff_lab.features.pit import build_pit_features
from mma_eff_lab.models.benchmark import benchmark_fight_models
from mma_eff_lab.models.calibrated import (
    CALIBRATED_CATBOOST_VERSION,
    train_calibrated_ufc_catboost,
)
from mma_eff_lab.models.calibrated_walkforward import evaluate_calibrated_walkforward
from mma_eff_lab.models.calibration import evaluate_model_calibration
from mma_eff_lab.models.dataset import write_model_dataset
from mma_eff_lab.models.model_card import write_model_card
from mma_eff_lab.models.predict import predict_card, predict_fight
from mma_eff_lab.models.quality import validate_model_quality
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
    train_calibrated = subparsers.add_parser("train-calibrated-ufc-catboost")
    train_calibrated.add_argument("--output-dir")
    benchmark_models = subparsers.add_parser("benchmark-fight-models")
    benchmark_models.add_argument("--output-path")
    benchmark_models.add_argument("--folds", type=int, default=8)
    benchmark_models.add_argument("--initial-train-fraction", type=float, default=0.5)
    quality = subparsers.add_parser("validate-model-quality")
    quality.add_argument("--benchmark-path")
    quality.add_argument("--output-path")
    calibrated_wf = subparsers.add_parser("evaluate-calibrated-walkforward")
    calibrated_wf.add_argument("--output-dir")
    calibrated_wf.add_argument("--folds", type=int, default=8)
    calibrated_wf.add_argument("--initial-train-fraction", type=float, default=0.5)
    calibrated_wf.add_argument("--bins", type=int, default=10)
    calibration = subparsers.add_parser("evaluate-model-calibration")
    calibration.add_argument("--output-dir")
    calibration.add_argument("--source", default="ufcstats")
    calibration.add_argument("--bins", type=int, default=10)
    predict_fight_parser = subparsers.add_parser("predict-fight")
    predict_fight_parser.add_argument("--fighter-a", required=True)
    predict_fight_parser.add_argument("--fighter-b", required=True)
    predict_fight_parser.add_argument("--event-date", required=True)
    predict_fight_parser.add_argument(
        "--model-version",
        default=CALIBRATED_CATBOOST_VERSION,
        choices=["xgboost_fight_outcome_v1", CALIBRATED_CATBOOST_VERSION],
    )
    predict_card_parser = subparsers.add_parser("predict-card")
    predict_card_parser.add_argument("--input", required=True)
    predict_card_parser.add_argument("--output")
    predict_card_parser.add_argument(
        "--model-version",
        default=CALIBRATED_CATBOOST_VERSION,
        choices=["xgboost_fight_outcome_v1", CALIBRATED_CATBOOST_VERSION],
    )
    subparsers.add_parser("make-reports")
    write_card = subparsers.add_parser("write-model-card")
    write_card.add_argument("--model-version", default=CALIBRATED_CATBOOST_VERSION)
    write_card.add_argument("--output-dir")
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
    elif args.command == "train-calibrated-ufc-catboost":
        result = train_calibrated_ufc_catboost(
            output_dir=Path(args.output_dir) if args.output_dir else None,
        )
    elif args.command == "benchmark-fight-models":
        result = benchmark_fight_models(
            output_path=Path(args.output_path) if args.output_path else None,
            folds=args.folds,
            initial_train_fraction=args.initial_train_fraction,
        )
    elif args.command == "validate-model-quality":
        result = validate_model_quality(
            benchmark_path=Path(args.benchmark_path) if args.benchmark_path else None,
            output_path=Path(args.output_path) if args.output_path else None,
        )
    elif args.command == "evaluate-calibrated-walkforward":
        result = evaluate_calibrated_walkforward(
            output_dir=Path(args.output_dir) if args.output_dir else None,
            folds=args.folds,
            initial_train_fraction=args.initial_train_fraction,
            bins=args.bins,
        )
    elif args.command == "evaluate-model-calibration":
        result = evaluate_model_calibration(
            output_dir=Path(args.output_dir) if args.output_dir else None,
            source=args.source,
            bins=args.bins,
        )
    elif args.command == "predict-fight":
        result = predict_fight(
            args.fighter_a,
            args.fighter_b,
            event_date=pd.to_datetime(args.event_date).date(),
            model_version=args.model_version,
        )
    elif args.command == "predict-card":
        result = predict_card(
            Path(args.input),
            output_path=Path(args.output) if args.output else None,
            model_version=args.model_version,
        )
    elif args.command == "make-reports":
        result = make_reports()
    elif args.command == "write-model-card":
        result = write_model_card(
            model_version=args.model_version,
            output_dir=Path(args.output_dir) if args.output_dir else None,
        )
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
