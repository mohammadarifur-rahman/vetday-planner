"""Pure functions behind the Streamlit UI: filtering, ranking, formatting, plan text."""

from dataclasses import dataclass
from datetime import date, time

from vetday.classify import window_minutes
from vetday.models import Offer

SLOTS: list[tuple[str, str]] = [
    ("breakfast", "Breakfast"),
    ("lunch", "Lunch"),
    ("dinner", "Dinner"),
    ("coffee_snack", "Coffee & snacks"),
]
# Suggested time for each slot when the offer's hours allow it.
DEFAULT_SLOT_TIME = {
    "breakfast": 8 * 60,
    "coffee_snack": 10 * 60,
    "lunch": 12 * 60 + 30,
    "dinner": 18 * 60,
    "errand": 14 * 60,
}
ELIGIBILITY_CHOICES = {
    "Veteran": {"veterans"},
    "Active duty": {"active_duty"},
    "Family / spouse": {"families", "spouses"},
}


@dataclass(frozen=True)
class Filters:
    day: date
    who: str = "Veteran"
    free_only: bool = False
    dine_in_ok: bool = True


def matches(offer: Offer, f: Filters) -> bool:
    if not offer.is_active_on(f.day):
        return False
    if not ELIGIBILITY_CHOICES[f.who] & set(offer.eligibility or ["veterans"]):
        return False
    if f.free_only and not offer.is_free:
        return False
    if not f.dine_in_ok and offer.dine_in_only:
        return False
    return True


def rank_key(offer: Offer) -> tuple:
    """Fully free first, then confirmed over needs-verification, then more sources."""
    return (not offer.is_free, offer.needs_verification, -len(offer.sources), offer.brand.lower())


def filter_offers(offers: list[Offer], f: Filters) -> list[Offer]:
    return sorted((o for o in offers if matches(o, f)), key=rank_key)


def by_slot(offers: list[Offer]) -> dict[str, list[Offer]]:
    food = [o for o in offers if o.category == "Food & Drink"]
    return {slot: [o for o in food if slot in o.meal_slots] for slot, _ in SLOTS}


def errands(offers: list[Offer]) -> list[Offer]:
    return [o for o in offers if o.category != "Food & Drink" and o.is_location_based]


# ---------- formatting ----------


def clock(minutes: int) -> str:
    t = time(minutes // 60 % 24, minutes % 60)
    return t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def format_window(window: str | None) -> str:
    """'05:00-12:00' -> '5 AM–12 PM'; 'open-16:00' -> 'Open–4 PM'."""
    if not window:
        return "Hours not listed"
    if window == "all day":
        return "All day"
    start, _, end = window.partition("-")
    s = "Open" if start == "open" else clock(int(start[:2]) * 60 + int(start[3:5]))
    e = "close" if end == "close" else clock(int(end[:2]) * 60 + int(end[3:5]))
    return f"{s}–{e}"


def _day(d: date) -> str:
    return f"{d:%b} {d.day}"


def format_dates(offer: Offer) -> str:
    if offer.start_date is None:
        return "Date not listed"
    if not offer.date_stated:
        return f"{_day(offer.start_date)} (assumed: source only says Veterans Day)"
    if offer.end_date and offer.end_date != offer.start_date:
        return f"{_day(offer.start_date)}–{_day(offer.end_date)}"
    return _day(offer.start_date)


def suggested_time(offer: Offer, slot: str) -> int:
    """Default slot time, nudged inside the offer's hours when they are known."""
    want = DEFAULT_SLOT_TIME.get(slot, 12 * 60)
    span = window_minutes(offer.time_window)
    if span is None:
        return want
    start, end = span
    return min(max(want, start), max(start, end - 30))


# ---------- the picked plan ----------


@dataclass(frozen=True)
class PlanItem:
    slot: str
    label: str
    offer: Offer
    minutes: int


def build_plan(picks: dict[str, Offer], errand_picks: list[Offer]) -> list[PlanItem]:
    labels = dict(SLOTS)
    items = [PlanItem(s, labels[s], o, suggested_time(o, s)) for s, o in picks.items() if o]
    items += [PlanItem("errand", "Errand", o, suggested_time(o, "errand")) for o in errand_picks]
    return sorted(items, key=lambda i: i.minutes)


def plan_text(items: list[PlanItem], day: date, zip_code: str) -> str:
    lines = [
        f"My Veterans Day plan - {day:%A, %b} {day.day}"
        + (f" (near {zip_code})" if zip_code else "")
    ]
    for it in items:
        o = it.offer
        flags = [
            f for f, on in (("dine-in only", o.dine_in_only), ("bring ID", o.id_required)) if on
        ]
        lines.append(
            f"~{clock(it.minutes)}  {it.label}: {o.brand} - {o.summary}"
            f" [{format_window(o.time_window)}{'; ' + ', '.join(flags) if flags else ''}]"
        )
    lines.append("Offers vary by location - verify participation with each location before you go.")
    return "\n".join(lines)
