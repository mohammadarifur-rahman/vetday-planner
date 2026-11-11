from datetime import date

from vetday.merge import merge_offers
from vetday.models import Offer, SourceRef

NAMES = {"VA News": "va_news", "TODAY": "today_com", "Blue Star Families": "bluestar"}


def offer(src, **kw):
    base = dict(
        id="chili--food-drink",
        brand="Chili’s",
        brand_key="chili",
        category="Food & Drink",
        summary="Free entrée",
        details="...",
        meal_slots=["lunch", "dinner"],
        start_date=date(2026, 11, 11),
        end_date=date(2026, 11, 11),
        sources=[SourceRef(name=src, url=f"https://{src}")],
    )
    return Offer(**{**base, **kw})


def test_same_brand_merges_and_va_wins():
    merged = merge_offers(
        [offer("Blue Star Families", summary="bluestar"), offer("VA News", summary="va")], NAMES
    )
    assert len(merged) == 1
    m = merged[0]
    assert m.summary == "va"
    assert [s.name for s in m.sources] == ["VA News", "Blue Star Families"]
    assert not m.conflicts and not m.needs_verification


def test_disagreements_are_recorded():
    merged = merge_offers(
        [
            offer("VA News", time_window="11:00-16:00"),
            offer("TODAY", time_window="11:00-15:00", start_date=date(2026, 11, 10)),
        ],
        NAMES,
    )
    m = merged[0]
    assert m.needs_verification
    assert any(c.startswith("Hours") for c in m.conflicts)
    assert any(c.startswith("Dates") for c in m.conflicts)
    assert m.time_window == "11:00-16:00"


def test_unstated_date_is_not_a_conflict():
    merged = merge_offers(
        [offer("VA News"), offer("TODAY", date_stated=False, start_date=date(2026, 11, 11))],
        NAMES,
    )
    assert not merged[0].conflicts


def test_same_source_twice_stays_separate():
    meal = offer("VA News", id="vcs--food-drink", brand_key="vcs")
    ipad = offer("VA News", id="vcs--retail-grocery", brand_key="vcs", category="Retail & Grocery")
    merged = merge_offers([meal, ipad], NAMES)
    assert len(merged) == 2


def test_category_mismatch_across_sources_still_merges():
    a = offer("VA News", id="kohl--retail-grocery", brand_key="kohl", category="Retail & Grocery")
    b = offer("TODAY", id="kohl--car-care", brand_key="kohl", category="Car Care")
    merged = merge_offers([b, a], NAMES)
    assert len(merged) == 1 and merged[0].category == "Retail & Grocery"


def test_generic_items_do_not_conflict():
    a = offer("VA News", items=["dine-in entrée"])
    b = offer("Blue Star Families", items=["free full-size entree"])
    c = offer("TODAY", items=["Oldtimer with Cheese", "Chicken Crispers"])
    assert not merge_offers([a, b, c], NAMES)[0].conflicts


def test_specific_items_conflict():
    a = offer("VA News", items=["ShackBurger"])
    b = offer("Blue Star Families", items=["Big Shack"])
    assert merge_offers([a, b], NAMES)[0].conflicts
