from datetime import date

import pytest

from vetday.classify import (
    brand_key,
    classify_category,
    meal_slots,
    parse_dates,
    parse_time_window,
    rule_fields,
    slots_from_window,
)

D = date


@pytest.mark.parametrize(
    "text,expected",
    [
        ("on Nov. 11, 2026, 5 a.m. to 12 p.m.; dine-in only", "05:00-12:00"),
        ("(available 11 a.m. - 6 p.m.)", "11:00-18:00"),
        ("a free breakfast from 6 to 10 a.m. at stores", "06:00-10:00"),
        ("from 4 p.m. to close on Wednesday", "16:00-close"),
        ("from open until 4 p.m., Veterans", "open-16:00"),
        ("from 7:30 am to 5:30 pm", "07:30-17:30"),
        ("a free Taquito on Nov. 11 until 11 a.m. local time", "open-11:00"),
        ("available all day in-restaurant", "all day"),
        ("a free $15 meal voucher on Nov. 11", None),
    ],
)
def test_time_window(text, expected):
    assert parse_time_window(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("on Nov. 10-11, 2026", (D(2026, 11, 10), D(2026, 11, 11), True)),
        ("On Nov. 10 and 11, Outback", (D(2026, 11, 10), D(2026, 11, 11), True)),
        ("From Nov. 6 through Nov. 12", (D(2026, 11, 6), D(2026, 11, 12), True)),
        ("Weekend (Nov. 6-9 & 11)", (D(2026, 11, 6), D(2026, 11, 11), True)),
        ("on Sunday, Nov. 8, 2026", (D(2026, 11, 8), D(2026, 11, 8), True)),
        # redemption windows never replace the day itself
        ("on Nov. 11. Bounce Back Card through Nov. 29.", (D(2026, 11, 11), D(2026, 11, 11), True)),
        (
            "a free entree on Veterans Day. Card for Nov. 12-29.",
            (D(2026, 11, 11), D(2026, 11, 11), True),
        ),
        ("free admission in November 2026", (D(2026, 11, 1), D(2026, 11, 30), True)),
        ("a free coffee for veterans", (D(2026, 11, 11), D(2026, 11, 11), False)),
    ],
)
def test_dates(text, expected):
    assert parse_dates(text) == expected


@pytest.mark.parametrize(
    "a,b",
    [
        ("Chili’s", "Chili's"),
        ("McCormick & Schmick’s", "McCormick and Schmick's"),
        ("Hard Rock Cafes", "Hard Rock Cafe"),
        ("The Greene Turtle ", "Greene Turtle"),
    ],
)
def test_brand_key_matches_variants(a, b):
    assert brand_key(a) == brand_key(b)


def test_brand_key_aliases():
    assert brand_key("Bubbakoo’s Burritos", {"bubbakoo burrito": "bubbakoo"}) == "bubbakoo"


def test_flags():
    r = rule_fields("Denny’s", "Free Grand Slam; dine-in only and ID required at participating")
    assert r.dine_in_only and r.id_required and r.participating_only and r.is_free
    r = rule_fields("Chipotle", "free chips and guac with a $5 purchase for veterans")
    assert not r.is_free  # needs a purchase -> not "fully free"
    assert r.eligibility == ["veterans"]
    r = rule_fields("Brinyte", "15% off site-wide with code BRINYTE15")
    assert r.likely_online
    r = rule_fields("Backyard Taco", "all seven locations in Arizona offer veterans a meal")
    assert r.region_note == "Only mentioned for: Arizona"


@pytest.mark.parametrize(
    "window,slots",
    [
        ("06:00-10:00", ["breakfast"]),
        ("05:00-12:00", ["breakfast"]),
        ("11:00-14:00", ["lunch"]),
        ("open-16:00", ["lunch"]),
        ("16:00-close", ["dinner"]),
        ("11:00-18:00", ["lunch", "dinner"]),
        ("all day", ["lunch", "dinner"]),
        (None, []),
    ],
)
def test_slots_from_window(window, slots):
    assert slots_from_window(window) == slots


def test_meal_slot_priority():
    food = "Food & Drink"
    assert meal_slots(food, "circle k", "one free medium hot or iced coffee", None) == [
        "coffee_snack"
    ]
    assert meal_slots(food, "x", "free breakfast biscuit sandwich and coffee", None) == [
        "breakfast"
    ]
    assert meal_slots(food, "golden corral", "free buffet", None) == ["dinner"]  # brand rule
    assert meal_slots(food, "x", "a free burger", "11:00-14:00") == ["lunch"]
    assert meal_slots(food, "x", "a free entrée", None, llm_slots=["breakfast"]) == ["breakfast"]
    assert meal_slots(food, "x", "free sub", None, llm_slots=["coffee_snack"]) == [
        "lunch",
        "dinner",
    ]
    assert meal_slots(food, "x", "a free entrée", None) == ["lunch", "dinner"]
    assert meal_slots("Car Care", "x", "free car wash", None) == ["any_time"]
    assert meal_slots(food, "x", "free coffee", None, override=["breakfast"]) == ["breakfast"]


@pytest.mark.parametrize(
    "brand,text,expected",
    [
        ("ZIPS Car Wash", "veterans get a free car wash", "Car Care"),
        ("Great Clips", "free haircut", "Personal Care"),
        ("Sheetz", "a free half turkey sub and a regular coffee", "Food & Drink"),
        (
            "Kohl’s",
            "veterans, retirees and families get 30% off their entire purchase",
            "Retail & Grocery",
        ),
        ("R. Riveter", "save 30% sitewide", "Online/Other"),
    ],
)
def test_category_keywords(brand, text, expected):
    assert classify_category(brand, text, None) == expected


def test_category_heading_wins():
    assert classify_category("X", "free car wash", "Food & Drink") == "Food & Drink"


def test_brand_name_does_not_drive_meal_slot():
    from vetday.classify import strip_brand

    text = strip_brand("Hot Dog on a Stick", "Hot Dog on a Stick offers a free 16 oz. lemonade")
    assert meal_slots("Food & Drink", "hot dog on a stick", text, None) == ["coffee_snack"]


def test_mentions_time_needs_a_clock_time():
    from vetday.classify import mentions_time

    assert not mentions_time("a free Original Grand Slam for the program")
    assert mentions_time("from 11 a.m. to 3 p.m.")
