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
from mma_eff_lab.parse.ufcstats import (
    BASE_URL,
    EVENTS_INDEX_URL,
    extract_id,
    parse_event_detail,
    parse_events_index,
    parse_fight_detail,
)


@dataclass(frozen=True)
class ManifestRecord:
    url: str
    source: str
    entity_type: str
    entity_id: str
    fetched_at_utc: str
    status_code: int
    sha256: str
    path: str


class UFCStatsDownloader:
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
        self.root = self.settings.raw_dir / "ufcstats"
        self.manifest_path = self.settings.raw_dir / "manifest.jsonl"

    def download_all(
        self,
        force: bool = False,
        limit_events: int | None = None,
        include_future: bool = False,
    ) -> dict[str, int]:
        ensure_data_dirs(self.settings)
        index_path = self._download(EVENTS_INDEX_URL, "events_index", "all", force=force)
        events = parse_events_index(index_path.read_text(encoding="utf-8"))
        discovered_count = len(events)
        if not include_future:
            today = date.today()
            events = [event for event in events if event.event_date <= today]
        if limit_events is not None:
            events = events[:limit_events]
        self.log(
            f"[ufcstats] discovered_events={discovered_count} selected_events={len(events)} "
            f"include_future={include_future} force={force}"
        )
        counts = {"events": 0, "fights": 0, "fighters": 0}
        for event_index, event in enumerate(events, start=1):
            self.log(
                f"[event {event_index}/{len(events)}] {event.event_date} {event.name} "
                f"event_id={event.event_id}"
            )
            event_path = self._download(event.url, "events", event.event_id, force=force)
            counts["events"] += 1
            result = parse_event_detail(
                event_path.read_text(encoding="utf-8"), event_id=event.event_id, url=event.url
            )
            for fight in result.fights:
                fight_path = self._download(fight.url, "fights", fight.fight_id, force=force)
                counts["fights"] += 1
                parsed_fight = parse_fight_detail(
                    fight_path.read_text(encoding="utf-8"),
                    event_id=event.event_id,
                    url=fight.url,
                )
                for participant in parsed_fight.participants:
                    fighter_url = f"{BASE_URL}/fighter-details/{participant.fighter_id}"
                    self._download(fighter_url, "fighters", participant.fighter_id, force=force)
                    counts["fighters"] += 1
            self.log(
                f"[event {event_index}/{len(events)} done] fights={len(result.fights)} "
                f"totals={counts}"
            )
        self.log(f"[ufcstats] complete totals={counts}")
        return counts

    def _download(self, url: str, entity_type: str, entity_id: str, force: bool) -> Path:
        path = self._path_for(entity_type, entity_id)
        if path.exists() and not force:
            self.log(f"[cache] {entity_type}/{entity_id}")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.log(f"[download] {entity_type}/{entity_id} {url}")
        response = self._get_with_retries(url)
        body = response.text
        path.write_text(body, encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self._append_manifest(
            ManifestRecord(
                url=url,
                source="ufcstats",
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
        if entity_type == "events_index":
            return self.root / "events_index.html"
        return self.root / entity_type / f"{entity_id}.html"

    def _append_manifest(self, record: ManifestRecord) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")


def infer_entity_id(url: str, entity_type: str) -> str:
    if entity_type == "events_index":
        return "all"
    singular = entity_type[:-1] if entity_type.endswith("s") else entity_type
    return extract_id(url, singular)


def download_ufcstats(
    force: bool = False,
    limit_events: int | None = None,
    include_future: bool = False,
    sleep_seconds: float = 1.0,
    settings: Settings | None = None,
) -> dict[str, int]:
    return UFCStatsDownloader(settings=settings, sleep_seconds=sleep_seconds).download_all(
        force=force, limit_events=limit_events, include_future=include_future
    )


def _default_log(message: str) -> None:
    print(message, flush=True)
