from __future__ import annotations

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

from mma_eff_lab.config import Settings, ensure_data_dirs, get_settings


def make_reports(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    outputs: dict[str, str] = {}
    if not settings.warehouse_path.exists():
        return outputs
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        events = conn.execute("select * from events").fetchdf()
        if not events.empty:
            events["event_date"] = pd.to_datetime(events["event_date"])
            by_year = events.groupby(events["event_date"].dt.year).size().reset_index(name="events")
            path = settings.reports_dir / "event_count_by_year.png"
            ax = by_year.plot(kind="bar", x="event_date", y="events", legend=False, figsize=(10, 4))
            ax.set_xlabel("Year")
            ax.set_ylabel("Events")
            plt.tight_layout()
            plt.savefig(path)
            plt.close()
            outputs["event_count_by_year"] = str(path)
        if _table_exists(conn, "pit_fighter_features"):
            features = conn.execute("select * from pit_fighter_features").fetchdf()
            if not features.empty:
                path = settings.reports_dir / "pit_feature_missingness.csv"
                features.isna().mean().sort_values(ascending=False).to_csv(
                    path, header=["missing_rate"]
                )
                outputs["pit_feature_missingness"] = str(path)
    return outputs


def _table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        conn.execute(
            "select 1 from information_schema.tables where table_schema='main' and table_name=?",
            [name],
        ).fetchone()
    )
