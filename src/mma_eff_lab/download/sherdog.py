from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import requests
from bs4 import BeautifulSoup, Tag

from mma_eff_lab.config import Settings, ensure_data_dirs, get_settings
from mma_eff_lab.download.ufcstats import ManifestRecord
from mma_eff_lab.parse.sherdog import (
    BASE_URL,
    SherdogEvent,
    SherdogFighter,
    absolute_url,
    extract_fighter_id,
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
    PromotionSeed(
        "dwcs",
        "Dana White's Contender Series",
        "12411",
        f"{BASE_URL}/organizations/Dana-Whites-Contender-Series-12411",
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

    def download_ufc_profile_searches(
        self,
        limit_fighters: int | None = None,
        fighters: list[dict[str, object]] | None = None,
    ) -> dict[str, int]:
        ensure_data_dirs(self.settings)
        fighters = fighters or _ufc_fighters_without_sherdog_link(self.settings)
        if limit_fighters is not None:
            fighters = fighters[:limit_fighters]
        counts = {
            "ufc_unlinked_fighters": len(fighters),
            "searched": 0,
            "unique_exact_matches": 0,
            "downloaded": 0,
            "already_cached": 0,
            "no_exact_match": 0,
            "ambiguous_exact_match": 0,
            "download_failures": 0,
            "search_failures": 0,
        }
        for fighter in fighters:
            name = str(fighter["full_name"])
            candidates: list[FightFinderCandidate] = []
            for search_name in _search_name_variants(name):
                search_url = f"{BASE_URL}/stats/fightfinder?{urlencode({'SearchTxt': search_name})}"
                self.log(
                    f"[sherdog search] ufcstats/{fighter['source_fighter_id']} "
                    f"{name} query={search_name}"
                )
                try:
                    response = self._get_with_retries(search_url)
                except RuntimeError as exc:
                    counts["search_failures"] += 1
                    self.log(f"[error] sherdog search {search_name} {exc}")
                    continue
                counts["searched"] += 1
                candidates = _fightfinder_exact_name_candidates(response.text, name)
                time.sleep(self.sleep_seconds)
                if candidates:
                    break
            if not candidates:
                counts["no_exact_match"] += 1
                continue
            if len(candidates) > 1:
                counts["ambiguous_exact_match"] += 1
                candidate_ids = ",".join(candidate.source_fighter_id for candidate in candidates)
                self.log(
                    f"[sherdog search ambiguous] {name} "
                    f"candidate_ids={candidate_ids}"
                )
                continue
            candidate = candidates[0]
            counts["unique_exact_matches"] += 1
            path = self._path_for("fighters", candidate.source_fighter_id)
            cached_before = path.exists()
            downloaded = self._download(
                candidate.url,
                "fighters",
                candidate.source_fighter_id,
                force=False,
                required=False,
            )
            if downloaded is None:
                counts["download_failures"] += 1
            elif cached_before:
                counts["already_cached"] += 1
            else:
                counts["downloaded"] += 1
        self.log(f"[sherdog search] profile_search_totals={counts}")
        return counts

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


def retry_missing_sherdog_fighters(
    sleep_seconds: float = 1.0,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    downloader = SherdogDownloader(settings=settings, sleep_seconds=sleep_seconds)
    ensure_data_dirs(settings)
    fighters = _missing_fighters_from_cached_events(settings)
    counts = {"missing_fighters": len(fighters), "downloaded": 0, "download_failures": 0}
    for fighter in fighters.values():
        path = downloader._download(
            fighter.url,
            "fighters",
            fighter.source_fighter_id,
            force=False,
            required=False,
        )
        if path is None:
            counts["download_failures"] += 1
        else:
            counts["downloaded"] += 1
    downloader.log(f"[sherdog repair] fighter_retry_totals={counts}")
    return counts


def download_sherdog_ufc_profiles(
    sleep_seconds: float = 1.0,
    limit_fighters: int | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    downloader = SherdogDownloader(settings=settings, sleep_seconds=sleep_seconds)
    return downloader.download_ufc_profile_searches(limit_fighters=limit_fighters)


def _missing_fighters_from_cached_events(settings: Settings) -> dict[str, SherdogFighter]:
    fighters: dict[str, SherdogFighter] = {}
    events_dir = settings.raw_dir / "sherdog" / "events"
    for path in sorted(events_dir.glob("*.html")):
        try:
            parsed = parse_event_detail(path.read_text(encoding="utf-8"), source_event_id=path.stem)
        except Exception:
            continue
        for fighter in parsed.fighters:
            fighter_path = (
                settings.raw_dir / "sherdog" / "fighters" / f"{fighter.source_fighter_id}.html"
            )
            if not fighter_path.exists():
                fighters[fighter.source_fighter_id] = fighter
    return fighters


@dataclass(frozen=True)
class FightFinderCandidate:
    source_fighter_id: str
    full_name: str
    url: str


def _ufc_fighters_without_sherdog_link(settings: Settings) -> list[dict[str, object]]:
    if not settings.warehouse_path.exists():
        raise FileNotFoundError(f"Warehouse not found: {settings.warehouse_path}")
    with duckdb.connect(str(settings.warehouse_path), read_only=True) as conn:
        frame = conn.execute(
            """
            with linked as (
              select distinct replace(canonical_fighter_id, 'ufcstats:', '') as source_fighter_id
              from fighter_identity_links
              where source = 'sherdog' and canonical_fighter_id like 'ufcstats:%'
            )
            select sf.source_fighter_id, sf.full_name
            from source_fighters sf
            left join linked using (source_fighter_id)
            where sf.source = 'ufcstats'
              and linked.source_fighter_id is null
            order by sf.full_name, sf.source_fighter_id
            """
        ).fetchdf()
    return frame.to_dict("records")


def _fightfinder_exact_name_candidates(html: str, query_name: str) -> list[FightFinderCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    query_key = _cleaned_search_name(query_name)
    candidates: dict[str, FightFinderCandidate] = {}
    for row in soup.select("table.fightfinder_result tr"):
        link = row.select_one("a[href*='/fighter/']")
        if not isinstance(link, Tag):
            continue
        full_name = _fighter_result_name(row, link)
        if _cleaned_search_name(full_name) != query_key:
            continue
        url = absolute_url(str(link.get("href", "")))
        source_fighter_id = extract_fighter_id(url)
        candidates[source_fighter_id] = FightFinderCandidate(
            source_fighter_id=source_fighter_id,
            full_name=full_name,
            url=url,
        )
    return list(candidates.values())


def _fighter_result_name(row: Tag, link: Tag) -> str:
    cells = row.select("td")
    for cell in cells:
        if cell.find("a", href=re.compile(r"/fighter/")) is not None:
            return " ".join(cell.stripped_strings)
    return " ".join(link.stripped_strings)


def _cleaned_search_name(value: str) -> str:
    value = re.sub(r'\s+"[^"]+"\s+', " ", str(value))
    tokens = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        if len(tokens[index]) == 1 and tokens[index].isalpha():
            start = index
            while index < len(tokens) and len(tokens[index]) == 1 and tokens[index].isalpha():
                index += 1
            if index - start > 1:
                collapsed.append("".join(tokens[start:index]))
            else:
                collapsed.append(tokens[start])
            continue
        collapsed.append(tokens[index])
        index += 1
    return " ".join(collapsed).strip()


def _search_name_variants(name: str) -> list[str]:
    parts = str(name).split()
    variants = [str(name)]
    if parts and len(parts[0]) in {2, 3} and parts[0].isalpha() and parts[0].isupper():
        dotted = ".".join(parts[0]) + "."
        spaced = " ".join(parts[0])
        suffix = " ".join(parts[1:])
        variants.append(f"{dotted} {suffix}".strip())
        variants.append(f"{spaced} {suffix}".strip())
    return list(dict.fromkeys(variants))


def _default_log(message: str) -> None:
    print(message, flush=True)
