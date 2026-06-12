from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from mma_eff_lab.config import get_settings
from mma_eff_lab.download.sherdog import (
    SherdogDownloader,
    _fightfinder_exact_name_candidates,
)
from mma_eff_lab.download.ufcstats import UFCStatsDownloader
from tests.test_sherdog_parser import (
    SHERDOG_BLUE_ID,
    SHERDOG_EVENT_ID,
    SHERDOG_RED_ID,
    sherdog_event_html,
    sherdog_fighter_html,
    sherdog_org_html,
)
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
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.headers: dict[str, str] = {}
        self.challenge_verified = False

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls.append(url)
        if self.challenge_verified and url in self.responses:
            solved_key = f"{url}#solved"
            if solved_key in self.responses:
                return FakeResponse(self.responses[solved_key])
        return FakeResponse(self.responses[url])

    def post(self, url: str, data: dict[str, str], timeout: float) -> FakeResponse:
        self.posts.append((url, data))
        self.challenge_verified = True
        return FakeResponse("", status_code=204)


def test_downloader_caches_and_skips_existing_files(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    responses = {
        "http://ufcstats.com/statistics/events/completed?page=all": event_index_html(),
        f"http://ufcstats.com/event-details/{EVENT_ID_1}": event_detail_html(),
        f"http://ufcstats.com/fight-details/{FIGHT_ID_1}": fight_detail_html(),
        f"http://ufcstats.com/fighter-details/{RED_ID}": fighter_html("Red Fighter"),
        f"http://ufcstats.com/fighter-details/{BLUE_ID}": fighter_html("Blue Fighter"),
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


def test_sherdog_downloader_caches_and_skips_existing_files(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    responses = {
        "https://www.sherdog.com/organizations/Bellator-MMA-1960": sherdog_org_html(),
        f"https://www.sherdog.com/events/Bellator-MMA-Bellator-116-{SHERDOG_EVENT_ID}": (
            sherdog_event_html()
        ),
        f"https://www.sherdog.com/fighter/Red-Fighter-{SHERDOG_RED_ID}": sherdog_fighter_html(
            "Red Fighter"
        ),
        f"https://www.sherdog.com/fighter/Blue-Fighter-{SHERDOG_BLUE_ID}": sherdog_fighter_html(
            "Blue Fighter"
        ),
    }
    session = FakeSession(responses)
    downloader = SherdogDownloader(settings=settings, session=session, sleep_seconds=0)
    downloader.download_all(promotion_set="major", limit_events=1)
    first_call_count = len(session.calls)
    downloader.download_all(promotion_set="major", limit_events=1)
    assert first_call_count == 4
    assert len(session.calls) == first_call_count
    assert (settings.raw_dir / "sherdog" / "events" / f"{SHERDOG_EVENT_ID}.html").exists()


def test_sherdog_fightfinder_exact_name_candidates_ignore_non_result_links() -> None:
    html = """
    <html><body>
      <a href="/fighter/Popular-Fighter-1">Nick Fiore</a>
      <table class="new_table fightfinder_result">
        <tr><th>Fighter</th><th>Nickname</th></tr>
        <tr>
          <td><a href="/fighter/Nick-De-Fiore-95819">Nick De Fiore</a></td>
          <td>"The Destroyer"</td>
        </tr>
        <tr>
          <td><a href="/fighter/Nick-Fiore-230223">Nick Fiore</a></td>
          <td></td>
        </tr>
      </table>
    </body></html>
    """

    candidates = _fightfinder_exact_name_candidates(html, "Nick Fiore")

    assert [candidate.source_fighter_id for candidate in candidates] == ["230223"]


def test_sherdog_fightfinder_exact_name_candidates_match_initials() -> None:
    html = """
    <html><body>
      <table class="new_table fightfinder_result">
        <tr><th>Fighter</th><th>Nickname</th></tr>
        <tr>
          <td><a href="/fighter/AJ-Fletcher-277255">A.J. Fletcher</a></td>
          <td></td>
        </tr>
      </table>
    </body></html>
    """

    candidates = _fightfinder_exact_name_candidates(html, "AJ Fletcher")

    assert [candidate.source_fighter_id for candidate in candidates] == ["277255"]


def test_sherdog_profile_search_skips_ambiguous_exact_name(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    search_url = "https://www.sherdog.com/stats/fightfinder?SearchTxt=Nick+Fiore"
    responses = {
        search_url: """
        <html><body>
          <table class="new_table fightfinder_result">
            <tr><th>Fighter</th><th>Nickname</th></tr>
            <tr><td><a href="/fighter/Nick-Fiore-230223">Nick Fiore</a></td></tr>
            <tr><td><a href="/fighter/Nick-Fiore-215571">Nick    Fiore</a></td></tr>
          </table>
        </body></html>
        """,
    }
    session = FakeSession(responses)
    downloader = SherdogDownloader(settings=settings, session=session, sleep_seconds=0)

    counts = downloader.download_ufc_profile_searches(
        fighters=[{"source_fighter_id": "u1", "full_name": "Nick Fiore"}]
    )

    assert counts["ambiguous_exact_match"] == 1
    assert counts["downloaded"] == 0


def test_sherdog_profile_search_tries_dotted_initial_variant(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    plain_url = "https://www.sherdog.com/stats/fightfinder?SearchTxt=AJ+Fletcher"
    dotted_url = "https://www.sherdog.com/stats/fightfinder?SearchTxt=A.J.+Fletcher"
    fighter_url = "https://www.sherdog.com/fighter/AJ-Fletcher-277255"
    responses = {
        plain_url: '<html><body><table class="new_table fightfinder_result"></table></body></html>',
        dotted_url: """
        <html><body>
          <table class="new_table fightfinder_result">
            <tr><th>Fighter</th><th>Nickname</th></tr>
            <tr><td><a href="/fighter/AJ-Fletcher-277255">A.J. Fletcher</a></td></tr>
          </table>
        </body></html>
        """,
        fighter_url: sherdog_fighter_html("A.J. Fletcher"),
    }
    session = FakeSession(responses)
    downloader = SherdogDownloader(settings=settings, session=session, sleep_seconds=0)

    counts = downloader.download_ufc_profile_searches(
        fighters=[{"source_fighter_id": "u1", "full_name": "AJ Fletcher"}]
    )

    assert counts["unique_exact_matches"] == 1
    assert counts["downloaded"] == 1
    assert session.calls == [plain_url, dotted_url, fighter_url]


def test_ufcstats_downloader_solves_browser_check(tmp_path: Path) -> None:
    settings = replace(get_settings(tmp_path), repo_root=tmp_path)
    gate_html = """
<!doctype html><html><body><p>Checking your browser...</p><script>
var nonce="abc123";
var target=new Array(2+1).join('0');
var xhr=new XMLHttpRequest();
xhr.open('POST',"/__c",true);
</script></body></html>
"""
    responses = {
        "http://ufcstats.com/statistics/events/completed?page=all": gate_html,
        "http://ufcstats.com/statistics/events/completed?page=all#solved": event_index_html(),
        f"http://ufcstats.com/event-details/{EVENT_ID_1}": event_detail_html(),
        f"http://ufcstats.com/fight-details/{FIGHT_ID_1}": fight_detail_html(),
        f"http://ufcstats.com/fighter-details/{RED_ID}": fighter_html("Red Fighter"),
        f"http://ufcstats.com/fighter-details/{BLUE_ID}": fighter_html("Blue Fighter"),
    }
    session = FakeSession(responses)
    downloader = UFCStatsDownloader(settings=settings, session=session, sleep_seconds=0)
    counts = downloader.download_all()
    assert counts["events"] == 1
    assert len(session.posts) == 1
    post_url, post_data = session.posts[0]
    assert post_url == "http://ufcstats.com/__c"
    assert post_data["nonce"] == "abc123"
    assert hashlib.sha256(f"abc123:{post_data['n']}".encode()).hexdigest().startswith("00")
