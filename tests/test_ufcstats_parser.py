from __future__ import annotations

from mma_eff_lab.parse.ufcstats import (
    parse_event_detail,
    parse_events_index,
    parse_fight_detail,
    parse_fighter_detail,
)

EVENT_ID_1 = "aaaaaaaaaaaaaaaa"
FIGHT_ID_1 = "bbbbbbbbbbbbbbbb"
RED_ID = "1111111111111111"
BLUE_ID = "2222222222222222"


def event_index_html() -> str:
    return f"""
    <table>
      <tr>
        <td><a href="http://ufcstats.com/event-details/{EVENT_ID_1}">
          UFC Test 1
        </a></td>
        <td>January 01, 2020</td>
        <td>Las Vegas, Nevada, USA</td>
      </tr>
    </table>
    """


def event_detail_html(event_id: str = EVENT_ID_1, fight_id: str = FIGHT_ID_1) -> str:
    return f"""
    <h2 class="b-content__title">UFC Test 1</h2>
    <ul class="b-list__box-list">
      <li>DATE: January 01, 2020</li>
      <li>LOCATION: Las Vegas, Nevada, USA</li>
    </ul>
    <table>
      <tr class="js-fight-details-click"
          data-link="http://ufcstats.com/fight-details/{fight_id}">
        <td>W L</td>
        <td>
          <a href="http://ufcstats.com/fighter-details/{RED_ID}">Red Fighter</a>
          <a href="http://ufcstats.com/fighter-details/{BLUE_ID}">Blue Fighter</a>
        </td>
        <td>KO/TKO</td>
        <td>2</td>
        <td>3:12</td>
      </tr>
    </table>
    <span>{event_id}</span>
    """


def fight_detail_html() -> str:
    return f"""
    <div>
      <i class="b-fight-details__person-status">W</i>
      <a href="http://ufcstats.com/fighter-details/{RED_ID}">Red Fighter</a>
      <i class="b-fight-details__person-status">L</i>
      <a href="http://ufcstats.com/fighter-details/{BLUE_ID}">Blue Fighter</a>
    </div>
    <table class="b-fight-details__table">
      <thead>
        <tr>
          <th>KD</th><th>SIG. STR.</th><th>TOTAL STR.</th><th>TD</th>
          <th>SUB. ATT</th><th>REV.</th><th>CTRL</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><p>1</p><p>0</p></td>
          <td><p>20 of 30</p><p>10 of 25</p></td>
          <td><p>40 of 55</p><p>30 of 60</p></td>
          <td><p>2 of 3</p><p>1 of 4</p></td>
          <td><p>1</p><p>0</p></td>
          <td><p>0</p><p>0</p></td>
          <td><p>1:30</p><p>0:30</p></td>
        </tr>
      </tbody>
    </table>
    """


def fighter_html(name: str = "Red Fighter", title_name: str | None = None) -> str:
    title_name = title_name or name
    return f"""
    <h2 class="b-content__title">{title_name}</h2>
    <ul>
      <li>Height: 5' 11"</li>
      <li>Weight: 170 lbs.</li>
      <li>Reach: 72"</li>
      <li>STANCE: Orthodox</li>
      <li>DOB: January 01, 1990</li>
    </ul>
    """


def test_parse_events_index_extracts_core_fields() -> None:
    events = parse_events_index(event_index_html())
    assert len(events) == 1
    assert events[0].event_id == EVENT_ID_1
    assert events[0].name == "UFC Test 1"
    assert str(events[0].event_date) == "2020-01-01"


def test_parse_event_detail_extracts_fight_and_participants() -> None:
    parsed = parse_event_detail(event_detail_html(), event_id=EVENT_ID_1)
    assert parsed.event.location == "Las Vegas, Nevada, USA"
    assert parsed.fights[0].winner_id == RED_ID
    assert parsed.fights[0].method == "KO/TKO"
    assert parsed.participants[0].corner == "red"
    assert parsed.participants[1].winner_flag is False


def test_parse_fight_detail_extracts_stats() -> None:
    parsed = parse_fight_detail(
        fight_detail_html(),
        event_id=EVENT_ID_1,
        url=f"http://ufcstats.com/fight-details/{FIGHT_ID_1}",
    )
    assert parsed.participants[0].winner_flag is True
    assert parsed.stats[0].sig_str_landed == 20
    assert parsed.stats[1].td_attempted == 4
    assert parsed.stats[0].ctrl_sec == 90


def test_parse_fighter_detail_optional_bio_fields() -> None:
    fighter = parse_fighter_detail(
        fighter_html(),
        url=f"http://ufcstats.com/fighter-details/{RED_ID}",
    )
    assert fighter.full_name == "Red Fighter"
    assert fighter.height_in == 71
    assert fighter.reach_in == 72
    assert str(fighter.dob) == "1990-01-01"


def test_parse_fighter_detail_strips_record_suffix_from_title_name() -> None:
    fighter = parse_fighter_detail(
        fighter_html(title_name="Red Fighter Record: 8-1-0"),
        url=f"http://ufcstats.com/fighter-details/{RED_ID}",
    )
    assert fighter.full_name == "Red Fighter"
