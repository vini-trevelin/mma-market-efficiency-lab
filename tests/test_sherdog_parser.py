from __future__ import annotations

from mma_eff_lab.parse.sherdog import parse_event_detail, parse_fighter_detail, parse_org_page

SHERDOG_EVENT_ID = "35263"
SHERDOG_RED_ID = "6166"
SHERDOG_BLUE_ID = "14639"


def sherdog_org_html(event_id: str = SHERDOG_EVENT_ID) -> str:
    return f"""
    <table class="new_table event">
      <tr class="table_head"><td>Date</td><td>Fight Title</td><td>Location</td></tr>
      <tr>
        <td>Apr<br>11<br>2014</td>
        <td><a href="/events/Bellator-MMA-Bellator-116-{event_id}">
          Bellator MMA - Bellator 116
        </a></td>
        <td>Pechanga Resort and Casino, Temecula, California, United States</td>
      </tr>
    </table>
    """


def sherdog_event_html(
    event_id: str = SHERDOG_EVENT_ID,
    red_id: str = SHERDOG_RED_ID,
    blue_id: str = SHERDOG_BLUE_ID,
    promotion: str = "Bellator MMA",
    weight_class: str = "Middleweight",
) -> str:
    return f"""
    <div class="event_detail">
      <h1>{promotion} - Test Event</h1>
      <a href="/organizations/Bellator-MMA-1960">{promotion}</a>
      Apr 11, 2014
      Pechanga Resort and Casino, Temecula, California, United States
    </div>
    <div class="fight_card">
      <div class="fighter left_side">
        <h3><a href="/fighter/Red-Fighter-{red_id}">Red Fighter</a></h3>
        <span class="final_result win">win</span>
      </div>
      <div class="versus"><span class="weight_class">{weight_class}</span></div>
      <div class="fighter right_side">
        <h3><a href="/fighter/Blue-Fighter-{blue_id}">Blue Fighter</a></h3>
        <span class="final_result loss">loss</span>
      </div>
    </div>
    <table class="fight_card_resume">
      <tr>
        <td><em>Match</em><br>1</td>
        <td><em>Method</em><br>Decision (Unanimous)</td>
        <td><em>Referee</em><br>John McCarthy</td>
        <td><em>Round</em><br>3</td>
        <td><em>Time</em><br>5:00</td>
      </tr>
    </table>
    """


def sherdog_fighter_html(name: str = "Red Fighter", dob: str = "Jan 1, 1990") -> str:
    return f"""
    <title>{name} MMA Stats, Pictures, News, Videos, Biography - Sherdog.com</title>
    <div class="fighter-data">
      AGE 34 / {dob}
      HEIGHT 5'11" / 180.34 cm
      WEIGHT 170 lbs / 77.11 kg
      ASSOCIATION Test Gym
      CLASS Welterweight
    </div>
    """


def test_parse_sherdog_org_page_extracts_event_rows() -> None:
    parsed = parse_org_page(
        sherdog_org_html(),
        promotion="Bellator MMA",
        organization_id="1960",
        url="https://www.sherdog.com/organizations/Bellator-MMA-1960",
    )
    assert len(parsed.events) == 1
    assert parsed.events[0].source_event_id == SHERDOG_EVENT_ID
    assert parsed.events[0].event_date.isoformat() == "2014-04-11"


def test_parse_sherdog_event_extracts_main_card_result() -> None:
    parsed = parse_event_detail(
        sherdog_event_html(),
        source_event_id=SHERDOG_EVENT_ID,
        url=f"https://www.sherdog.com/events/Bellator-MMA-Bellator-116-{SHERDOG_EVENT_ID}",
    )
    assert parsed.event.promotion == "Bellator MMA"
    assert len(parsed.fights) == 1
    assert parsed.fights[0].source_fight_id == f"{SHERDOG_EVENT_ID}:1"
    assert parsed.participants[0].winner_flag is True
    assert parsed.participants[1].outcome == "L"


def test_parse_sherdog_event_quarantines_non_mma_one_bout() -> None:
    parsed = parse_event_detail(
        sherdog_event_html(promotion="ONE Championship", weight_class="Flyweight Muay Thai"),
        source_event_id=SHERDOG_EVENT_ID,
        url=f"https://www.sherdog.com/events/ONE-Test-{SHERDOG_EVENT_ID}",
    )
    assert parsed.fights == []
    assert parsed.quarantine[0].reason == "ambiguous_or_non_mma_one_bout"


def test_parse_sherdog_fighter_detail_extracts_bio() -> None:
    fighter = parse_fighter_detail(
        sherdog_fighter_html(),
        url=f"https://www.sherdog.com/fighter/Red-Fighter-{SHERDOG_RED_ID}",
    )
    assert fighter.full_name == "Red Fighter"
    assert fighter.height_in == 71
    assert fighter.weight_lbs == 170
    assert fighter.dob.isoformat() == "1990-01-01"
