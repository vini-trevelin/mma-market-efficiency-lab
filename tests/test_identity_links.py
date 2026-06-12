from __future__ import annotations

import pandas as pd

from mma_eff_lab.warehouse.build import _identity_links


def _source_fighter(
    source: str,
    source_fighter_id: str,
    full_name: str,
    dob: str,
) -> dict[str, object]:
    return {
        "source": source,
        "source_fighter_id": source_fighter_id,
        "full_name": full_name,
        "height_in": 70,
        "weight_lbs": 170,
        "reach_in": None,
        "stance": None,
        "dob": pd.to_datetime(dob).date(),
        "url": f"https://example.test/{source}/{source_fighter_id}",
    }


def test_identity_links_match_unique_cleaned_name_with_near_dob() -> None:
    source_fighters = pd.DataFrame(
        [
            _source_fighter("ufcstats", "u1", "Jeremy Stephens", "1986-05-25"),
            _source_fighter("sherdog", "s1", 'Jeremy "Lil Heathen" Stephens', "1986-05-26"),
        ]
    )
    links = _identity_links(source_fighters, pd.DataFrame())

    row = links[links["source"] == "sherdog"].iloc[0]
    assert row["canonical_fighter_id"] == "ufcstats:u1"
    assert row["link_method"] == "cleaned_name_dob_near"


def test_identity_links_match_unique_cleaned_name_with_month_day_swap() -> None:
    source_fighters = pd.DataFrame(
        [
            _source_fighter("ufcstats", "u1", "Joshua Burkman", "1980-04-10"),
            _source_fighter("sherdog", "s1", 'Joshua "The People" Burkman', "1980-10-04"),
        ]
    )
    links = _identity_links(source_fighters, pd.DataFrame())

    row = links[links["source"] == "sherdog"].iloc[0]
    assert row["canonical_fighter_id"] == "ufcstats:u1"
    assert row["link_method"] == "cleaned_name_dob_month_day_swap"


def test_identity_links_match_unique_cleaned_name_with_same_year_close_dob() -> None:
    source_fighters = pd.DataFrame(
        [
            _source_fighter("ufcstats", "u1", "Tyron Woodley", "1982-04-07"),
            _source_fighter("sherdog", "s1", 'Tyron "The Chosen One" Woodley', "1982-04-17"),
        ]
    )
    links = _identity_links(source_fighters, pd.DataFrame())

    row = links[links["source"] == "sherdog"].iloc[0]
    assert row["canonical_fighter_id"] == "ufcstats:u1"
    assert row["link_method"] == "cleaned_name_dob_same_year_close"


def test_identity_links_match_initials_in_cleaned_names() -> None:
    source_fighters = pd.DataFrame(
        [
            _source_fighter("ufcstats", "u1", "AJ Fletcher", "1997-02-18"),
            _source_fighter("sherdog", "s1", "A.J. Fletcher", "1997-02-18"),
        ]
    )
    links = _identity_links(source_fighters, pd.DataFrame())

    row = links[links["source"] == "sherdog"].iloc[0]
    assert row["canonical_fighter_id"] == "ufcstats:u1"
    assert row["link_method"] == "exact_name_dob"


def test_identity_links_reject_unique_name_with_conflicting_dob() -> None:
    source_fighters = pd.DataFrame(
        [
            _source_fighter("ufcstats", "u1", "Jean Silva", "1996-12-27"),
            _source_fighter("sherdog", "s1", 'Jean "White Bear" Silva', "1977-06-20"),
        ]
    )
    links = _identity_links(source_fighters, pd.DataFrame())

    row = links[links["source"] == "sherdog"].iloc[0]
    assert row["canonical_fighter_id"] == "sherdog:s1"
    assert row["link_method"] == "source_self"


def test_identity_links_reject_unique_name_with_large_same_year_dob_gap() -> None:
    source_fighters = pd.DataFrame(
        [
            _source_fighter("ufcstats", "u1", "Marco Tulio", "1994-06-13"),
            _source_fighter("sherdog", "s1", 'Marco "Matuto" Tulio', "1994-08-30"),
        ]
    )
    links = _identity_links(source_fighters, pd.DataFrame())

    row = links[links["source"] == "sherdog"].iloc[0]
    assert row["canonical_fighter_id"] == "sherdog:s1"
    assert row["link_method"] == "source_self"
