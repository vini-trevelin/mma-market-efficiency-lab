from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    data_dir: Path
    raw_dir: Path
    warehouse_dir: Path
    reports_dir: Path
    logs_dir: Path
    warehouse_path: Path


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / "pyproject.toml").exists() or (path / ".git").exists():
            return path
    return current


def get_settings(repo_root: Path | None = None) -> Settings:
    root = (repo_root or find_repo_root()).resolve()
    data_dir = root / "data"
    return Settings(
        repo_root=root,
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        warehouse_dir=data_dir / "warehouse",
        reports_dir=data_dir / "reports",
        logs_dir=data_dir / "logs",
        warehouse_path=data_dir / "warehouse" / "mma.duckdb",
    )


def ensure_data_dirs(settings: Settings) -> None:
    for path in [settings.raw_dir, settings.warehouse_dir, settings.reports_dir, settings.logs_dir]:
        path.mkdir(parents=True, exist_ok=True)
