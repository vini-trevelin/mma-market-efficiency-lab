from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from mma_eff_lab.config import get_settings
from mma_eff_lab.download.ufcstats import UFCStatsDownloader
from tests.test_ufcstats_parser import (
    BLUE_ID,
    EVENT_ID_1,
    FIGHT_ID_1,
    RED_ID,
    event_detail_html,
    event_index_html,
    fight_detail_html,
    fighter_html,
)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls.append(url)
        return FakeResponse(self.responses[url])


def test_downloader_caches_and_skips_existing_files(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    responses = {
        "https://www.ufcstats.com/statistics/events/completed?page=all": event_index_html(),
        f"http://ufcstats.com/event-details/{EVENT_ID_1}": event_detail_html(),
        f"http://ufcstats.com/fight-details/{FIGHT_ID_1}": fight_detail_html(),
        f"https://www.ufcstats.com/fighter-details/{RED_ID}": fighter_html("Red Fighter"),
        f"https://www.ufcstats.com/fighter-details/{BLUE_ID}": fighter_html("Blue Fighter"),
    }
    session = FakeSession(responses)
    downloader = UFCStatsDownloader(settings=settings, session=session, sleep_seconds=0)
    counts = downloader.download_all()
    first_call_count = len(session.calls)
    downloader.download_all()
    assert counts["events"] == 1
    assert first_call_count == 5
    assert len(session.calls) == first_call_count
    assert (settings.raw_dir / "manifest.jsonl").exists()
