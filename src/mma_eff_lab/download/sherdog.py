from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import requests

from mma_eff_lab.config import Settings, ensure_data_dirs, get_settings
from mma_eff_lab.download.ufcstats import ManifestRecord
from mma_eff_lab.parse.sherdog import (
    BASE_URL,
    SherdogEvent,
    parse_event_detail,
    parse_org_page,
)


@dataclass(frozen=True)
class PromotionSeed:
    slug: str
    name: str
    organization_id: str
    url: str


MAJOR_PROMOTIONS = [
    PromotionSeed(
        "bellator", "Bellator MMA", "1960", f"{BASE_URL}/organizations/Bellator-MMA-1960"
    ),
    PromotionSeed(
        "pfl",
        "Professional Fighters League",
        "12241",
        f"{BASE_URL}/organizations/Professional-Fighters-League-12241",
    ),
    PromotionSeed(
        "wsof",
        "World Series of Fighting",
        "5449",
        f"{BASE_URL}/organizations/World-Series-of-Fighting-5449",
    ),
    PromotionSeed(
        "one",
        "ONE Championship",
        "3877",
        f"{BASE_URL}/organizations/ONE-Championship-3877",
    ),
    PromotionSeed(
        "pride",
        "Pride Fighting Championships",
        "3",
        f"{BASE_URL}/organizations/Pride-Fighting-Championships-3",
    ),
    PromotionSeed("strikeforce", "Strikeforce", "716", f"{BASE_URL}/organizations/Strikeforce-716"),
    PromotionSeed(
        "rizin",
        "Rizin Fighting Federation",
        "10333",
        f"{BASE_URL}/organizations/Rizin-Fighting-Federation-10333",
    ),
    PromotionSeed("dream", "Dream", "1357", f"{BASE_URL}/organizations/Dream-1357"),
    PromotionSeed(
        "invicta",
        "Invicta Fighting Championships",
        "4469",
        f"{BASE_URL}/organizations/Invicta-Fighting-Championships-4469",
    ),
]

PROMOTION_SETS = {"major": MAJOR_PROMOTIONS}


class SherdogDownloader:
    def __init__(
        self,
        settings: Settings | None = None,
        session: requests.Session | None = None,
        sleep_seconds: float = 1.0,
        timeout_seconds: float = 30.0,
        retries: int = 3,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session or requests.Session()
        self.sleep_seconds = sleep_seconds
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.log = log or _default_log
        self.root = self.settings.raw_dir / "sherdog"
        self.manifest_path = self.settings.raw_dir / "manifest.jsonl"
        self._organization_pages_downloaded = 0
        self.session.headers.update(
            {
                "User-Agent": (
                    "mma-market-efficiency-lab/0.1 "
                    "(local research cache; contact: local-user)"
                )
            }
        )

    def download_all(
        self,
        promotion_set: str = "major",
        force: bool = False,
        limit_events: int | None = None,
        include_future: bool = False,
    ) -> dict[str, int]:
        ensure_data_dirs(self.settings)
        seeds = PROMOTION_SETS[promotion_set]
        self._organization_pages_downloaded = 0
        discovered = self._discover_events(seeds, force=force, limit_events=limit_events)
        today = date.today()
        selected = [
            event for event in discovered if include_future or event.event_date <= today
        ]
        if limit_events is not None:
            selected = selected[:limit_events]
        self.log(
            f"[sherdog] discovered_events={len(discovered)} selected_events={len(selected)} "
            f"promotion_set={promotion_set} include_future={include_future} force={force}"
        )
        counts = {
            "organization_pages": self._organization_pages_downloaded,
            "events": 0,
            "fighters": 0,
            "download_failures": 0,
        }
        for event_index, event in enumerate(selected, start=1):
            self.log(
                f"[sherdog event {event_index}/{len(selected)}] {event.event_date} "
                f"{event.promotion} {event.name} event_id={event.source_event_id}"
            )
            event_path = self._download(
                event.url, "events", event.source_event_id, force=force, required=False
            )
            if event_path is None:
                counts["download_failures"] += 1
                continue
            counts["events"] += 1
            try:
                parsed = parse_event_detail(
                    event_path.read_text(encoding="utf-8"),
                    source_event_id=event.source_event_id,
                    promotion_hint=event.promotion,
                    url=event.url,
                )
            except Exception as exc:
                counts["download_failures"] += 1
                self.log(f"[sherdog parse error] event_id={event.source_event_id} {exc}")
                continue
            for fighter in parsed.fighters:
                fighter_path = self._download(
                    fighter.url,
                    "fighters",
                    fighter.source_fighter_id,
                    force=force,
                    required=False,
                )
                if fighter_path is None:
                    counts["download_failures"] += 1
                else:
                    counts["fighters"] += 1
            self.log(f"[sherdog event {event_index}/{len(selected)} done] totals={counts}")
        self.log(f"[sherdog] complete totals={counts}")
        return counts

    def _discover_events(
        self, seeds: list[PromotionSeed], force: bool, limit_events: int | None
    ) -> list[SherdogEvent]:
        events_by_id: dict[str, SherdogEvent] = {}
        for seed in seeds:
            page_url: str | None = seed.url
            page_number = 1
            while page_url:
                entity_id = f"{seed.organization_id}-page-{page_number}"
                path = self._download(page_url, "organizations", entity_id, force=force)
                self._organization_pages_downloaded += 1
                result = parse_org_page(
                    path.read_text(encoding="utf-8"),
                    promotion=seed.name,
                    organization_id=seed.organization_id,
                    url=page_url,
                )
                for event in result.events:
                    events_by_id.setdefault(event.source_event_id, event)
                self.log(
                    f"[sherdog org] {seed.slug} page={page_number} "
                    f"events_seen={len(events_by_id)}"
                )
                if limit_events is not None and len(events_by_id) >= limit_events:
                    break
                page_url = result.older_url
                page_number += 1
            if limit_events is not None and len(events_by_id) >= limit_events:
                break
        return sorted(events_by_id.values(), key=lambda item: item.event_date, reverse=True)

    def _download(
        self, url: str, entity_type: str, entity_id: str, force: bool, required: bool = True
    ) -> Path | None:
        path = self._path_for(entity_type, entity_id)
        if path.exists() and not force:
            self.log(f"[cache] sherdog {entity_type}/{entity_id}")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log(f"[download] sherdog {entity_type}/{entity_id} {url}")
        try:
            response = self._get_with_retries(url)
        except RuntimeError as exc:
            self.log(f"[error] sherdog {entity_type}/{entity_id} {url} {exc}")
            if required:
                raise
            return None
        body = response.text
        path.write_text(body, encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self._append_manifest(
            ManifestRecord(
                url=url,
                source="sherdog",
                entity_type=entity_type,
                entity_id=entity_id,
                fetched_at_utc=datetime.now(UTC).isoformat(),
                status_code=response.status_code,
                sha256=digest,
                path=str(path.relative_to(self.settings.repo_root)),
            )
        )
        time.sleep(self.sleep_seconds)
        return path

    def _get_with_retries(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for _attempt in range(self.retries):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(self.sleep_seconds)
        raise RuntimeError(f"Failed to download {url}: {last_error}") from last_error

    def _path_for(self, entity_type: str, entity_id: str) -> Path:
        return self.root / entity_type / f"{entity_id}.html"

    def _append_manifest(self, record: ManifestRecord) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")


def download_sherdog(
    promotion_set: str = "major",
    force: bool = False,
    limit_events: int | None = None,
    include_future: bool = False,
    sleep_seconds: float = 1.0,
    settings: Settings | None = None,
) -> dict[str, int]:
    return SherdogDownloader(settings=settings, sleep_seconds=sleep_seconds).download_all(
        promotion_set=promotion_set,
        force=force,
        limit_events=limit_events,
        include_future=include_future,
    )


def _default_log(message: str) -> None:
    print(message, flush=True)
