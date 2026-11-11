from datetime import date

from vetday.geo import maps_search_url, offer_maps_url
from vetday.models import Offer, SourceRef
from vetday.planner import (
    Filters,
    build_plan,
    by_slot,
    filter_offers,
    format_dates,
    format_window,
    plan_text,
)

DAY = date(2026, 11, 11)


def offer(brand, **kw):
    base = dict(
        id=brand.lower(),
        brand=brand,
        brand_key=brand.lower(),
        category="Food & Drink",
        summary=f"{brand} deal",
        details="...",
        meal_slots=["lunch", "dinner"],
        start_date=DAY,
        end_date=DAY,
        eligibility=["veterans", "active_duty"],
        sources=[SourceRef(name="VA News", url="https://news.va.gov")],
    )
    return Offer(**{**base, **kw})


def test_filters():
    offers = [
        offer("Free", is_free=True),
        offer("Discount"),
        offer("DineIn", dine_in_only=True, is_free=True),
        offer("Nov8", start_date=date(2026, 11, 8), end_date=date(2026, 11, 8)),
        offer("SpouseOnly", eligibility=["spouses"]),
    ]
    names = [o.brand for o in filter_offers(offers, Filters(DAY))]
    assert names[0] in {"DineIn", "Free"} and "Nov8" not in names and "SpouseOnly" not in names
    assert [o.brand for o in filter_offers(offers, Filters(DAY, free_only=True))] == [
        "DineIn",
        "Free",
    ]
    assert "DineIn" not in [o.brand for o in filter_offers(offers, Filters(DAY, dine_in_ok=False))]
    assert [o.brand for o in filter_offers(offers, Filters(DAY, who="Family / spouse"))] == [
        "SpouseOnly"
    ]


def test_ranking_prefers_free_then_confirmed():
    offers = [offer("A", needs_verification=True, is_free=True), offer("B", is_free=True)]
    assert [o.brand for o in filter_offers(offers, Filters(DAY))] == ["B", "A"]


def test_by_slot_only_food():
    offers = [offer("Pancakes", meal_slots=["breakfast"]), offer("Wash", category="Car Care")]
    slots = by_slot(offers)
    assert [o.brand for o in slots["breakfast"]] == ["Pancakes"]
    assert slots["lunch"] == []


def test_formatting():
    assert format_window("05:00-12:00") == "5 AM–12 PM"
    assert format_window("open-16:00") == "Open–4 PM"
    assert format_window("16:00-close") == "4 PM–close"
    assert format_window("07:30-17:30") == "7:30 AM–5:30 PM"
    assert format_window(None) == "Hours not listed"
    assert format_dates(offer("X", end_date=date(2026, 11, 12))) == "Nov 11–Nov 12"
    assert "assumed" in format_dates(offer("X", date_stated=False))


def test_plan_orders_by_time_and_respects_hours():
    picks = {
        "dinner": offer("Golden Corral", time_window="16:00-close"),
        "breakfast": offer("Denny's", time_window="05:00-12:00"),
        "lunch": offer("Late Lunch", time_window="13:00-15:00"),
    }
    items = build_plan(picks, [offer("Great Clips", category="Personal Care")])
    assert [i.offer.brand for i in items] == [
        "Denny's",
        "Late Lunch",
        "Great Clips",
        "Golden Corral",
    ]
    assert items[1].minutes == 13 * 60  # nudged into the 1-3 PM window
    text = plan_text(items, DAY, "32801")
    assert "near 32801" in text and "verify participation" in text.lower()


def test_maps_links():
    url = maps_search_url("Denny’s", "32801")
    assert url.startswith("https://www.google.com/maps/search/?api=1&query=")
    assert "near+32801" in url
    assert offer_maps_url(offer("Online", is_location_based=False), "32801") is None
    vcs = offer("Veterans Canteen Service (VCS)", brand_key="veteran canteen service")
    assert "VA+medical+center" in offer_maps_url(vcs, "32801")
