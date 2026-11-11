"""Deterministic rules: brand keys, dates, time windows, flags, category, meal slots."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from vetday.config import VETERANS_DAY, YEAR

# ---------- brand keys ----------

_GENERIC_TAIL = re.compile(r"\b(restaurants?|inc|llc|co)$")


def brand_key(brand: str, aliases: dict[str, str] | None = None) -> str:
    """'Chili’s' -> 'chili', 'McCormick & Schmick's' -> 'mccormick and schmick'."""
    s = brand.replace("\u2019", "'").replace("\u2018", "'")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)  # drop "(VA)", "(Abilene, Kansas)"
    s = re.sub(r"['`]s\b", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = [
        w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in s.split()
    ]
    s = " ".join(words).removeprefix("the ").strip()
    s = _GENERIC_TAIL.sub("", s).strip()
    return (aliases or {}).get(s, s)


# ---------- times ----------

_T = r"(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?|noon)?"
_TIME_RANGE = re.compile(
    rf"(?<![\d$.,])(?:{_T}|(open))\s*(?:-|to|until|till|and)\s*(?:{_T}|(close))", re.I
)
_UNTIL = re.compile(rf"\b(?:until|before|till)\s+{_T}", re.I)
_MONTH_BEFORE = re.compile(r"(?:Oct|Nov|Dec)[a-z]*\.?\s*$", re.I)
_ALL_DAY = re.compile(r"\ball[- ]day\b|\ball \d+ hours\b", re.I)


def _to_minutes(hour: str, minute: str | None, ampm: str | None) -> int:
    h, m = int(hour), int(minute or 0)
    tag = (ampm or "").lower().replace(".", "").replace(" ", "")
    if tag == "noon":
        return 12 * 60
    if tag == "pm" and h != 12:
        h += 12
    if tag == "am" and h == 12:
        h = 0
    return h * 60 + m


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_time_window(text: str) -> str | None:
    """'5 a.m. to 12 p.m.' -> '05:00-12:00'; 'from 4 p.m. to close' -> '16:00-close'."""
    for m in _TIME_RANGE.finditer(text):
        h1, m1, ap1, opened, h2, m2, ap2, closed = m.groups()
        if not (ap1 or ap2) or (opened and closed):
            continue
        if h1 and _MONTH_BEFORE.search(text[: m.start()]):
            continue  # "Nov. 11 until 11 a.m." is a date, not a start time
        if h1 and int(h1) > 12 or h2 and int(h2) > 12:
            continue
        end = "close" if closed else None
        if h2:
            end_min = _to_minutes(h2, m2, ap2 or ap1)
            end = _fmt(end_min)
        if opened:
            return f"open-{end}"
        start_min = _to_minutes(h1, m1, ap1 or ap2)
        if not ap1 and h2 and start_min > end_min:  # "11 to 2 p.m."
            start_min = _to_minutes(h1, m1, "am")
        return f"{_fmt(start_min)}-{end}"
    for m in _UNTIL.finditer(text):
        if m[3]:
            return f"open-{_fmt(_to_minutes(m[1], m[2], m[3]))}"
    if _ALL_DAY.search(text):
        return "all day"
    return None


def window_minutes(window: str | None) -> tuple[int, int] | None:
    if not window or window == "all day":
        return None
    start, _, end = window.partition("-")
    s = 6 * 60 if start == "open" else int(start[:2]) * 60 + int(start[3:5])
    e = 23 * 60 + 59 if end == "close" else int(end[:2]) * 60 + int(end[3:5])
    return s, e


# ---------- dates ----------

_MONTHS = {"oct": 10, "nov": 11, "dec": 12}
_M = r"(Oct|Nov|Dec)[a-z]*\.?"
_D = r"(\d{1,2})(?:st|nd|rd|th)?"
_SEP = r"\s*(?:-|to|through|thru|until)\s*"
_CROSS = re.compile(rf"\b{_M}\s+{_D}(?:,\s*{YEAR})?{_SEP}{_M}\s+{_D}", re.I)
_SAME = re.compile(
    rf"\b{_M}\s+{_D}(?:{_SEP}|\s*(?:and|&|or)\s*){_D}\b(?:\s*(?:&|and)\s*{_D}\b)?", re.I
)
_SINGLE = re.compile(rf"\b{_M}\s+{_D}\b", re.I)
_END_BOUND = re.compile(r"(?:through|thru|until|by|before)\s*$", re.I)
_TARGET_DAY = re.compile(
    r"veterans day|the holiday|\b(?:Nov|November)\.?\s+11\b|\bon Wednesday\b", re.I
)
_WHOLE_MONTH = re.compile(r"\b(?:in|month of|throughout|all of)\s+November\b", re.I)
_LAST_YEAR = re.compile(r"\blast year\b|\beach year\b|\bannual(?:ly)?\b|\bevery year\b", re.I)


def _d(month: str, day: str) -> date | None:
    try:
        return date(YEAR, _MONTHS[month[:3].lower()], int(day))
    except ValueError:
        return None


def parse_dates(text: str, target: date = VETERANS_DAY) -> tuple[date, date, bool]:
    """Return (start, end, explicit).

    Priority: a stated span covering the target day > "Veterans Day"/"Nov. 11" wording >
    an end bound like "through Nov. 12" > the first other date > "in November".
    Secondary dates (voucher redemption windows) never override the day itself."""
    spans: list[tuple[int, date, date]] = []
    bounds: list[tuple[int, date, date]] = []
    for m in _CROSS.finditer(text):
        a, b = _d(m[1], m[2]), _d(m[3], m[4])
        if a and b:
            spans.append((m.start(), a, b))
    for m in _SAME.finditer(text):
        a, b = _d(m[1], m[2]), _d(m[1], m[4] or m[3])
        if a and b and a <= b:
            spans.append((m.start(), a, b))
    covered = [(s, e) for _, s, e in spans]
    for m in _SINGLE.finditer(text):
        d = _d(m[1], m[2])
        if not d or any(s <= d <= e for s, e in covered):
            continue
        if _END_BOUND.search(text[: m.start()]):
            bounds.append((m.start(), min(target, d), d))
        else:
            spans.append((m.start(), d, d))
    for _, s, e in sorted(spans):
        if s <= target <= e:
            return s, e, True
    if _TARGET_DAY.search(text):
        return target, target, True
    for _, s, e in sorted(bounds):
        if s <= target <= e:
            return s, e, True
    if spans:
        _, s, e = min(spans)
        return s, e, True
    if _WHOLE_MONTH.search(text):
        return date(YEAR, 11, 1), date(YEAR, 11, 30), True
    return target, target, False


# ---------- flags ----------

_DINE_IN = re.compile(r"\bdine[- ]?in\b|\bdining in\b|in-restaurant", re.I)
_ID = re.compile(
    r"\bID\b|identification|proof of (?:military )?service|ID\.me|DD-?214|military card"
    r"|veterans? card|verif(?:y|ied) (?:military|status)",
)
_PARTICIPATING = re.compile(r"participating|select locations|at select|some locations", re.I)
_FREE = re.compile(r"\bfree\b|complimentary|on the house|no charge", re.I)
_NEEDS_PURCHASE = re.compile(
    r"buy one|BOGO|with (?:the |any |a |an )?(?:\$\d+ )?(?:minimum )?(?:\w+ )?purchase"
    r"|purchase of|when purchasing|with a drink purchase|minimum purchase",
    re.I,
)
_ONLINE = re.compile(
    r"\bonline\b|sitewide|site-wide|website|\bcode\b|ID\.me at checkout|\bbook\b|membership",
    re.I,
)
_IN_PERSON = re.compile(
    r"in-store|in store|locations?|dine|restaurant|stores?\b|salon|shop(?:s)?\b|visit|museum"
    r"|admission|wash",
    re.I,
)
_ELIGIBILITY = {
    "veterans": re.compile(r"veteran|retire", re.I),
    "active_duty": re.compile(
        r"active[- ]?duty|service ?members?|military (?:members?|personnel)|troops"
        r"|reserv|national guard|active military|current military",
        re.I,
    ),
    "families": re.compile(r"famil|dependents|gold star", re.I),
    "spouses": re.compile(r"spouse", re.I),
    "first_responders": re.compile(r"first responder", re.I),
}
_STATES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia"
    "|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland"
    "|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada"
    "|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma"
    "|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah"
    "|Vermont|Virginia|Washington, D\\.C\\.|Washington|West Virginia|Wisconsin|Wyoming"
    "|Northeast|Midwest|Southeast|Pacific Northwest"
)
_REGION = re.compile(rf"\b({_STATES})\b")


_TIME_WORDS = re.compile(
    r"\d\s*(?:a\.?m\b|p\.?m\b)|\bnoon\b|\ball[- ]day\b|\bto close\b|\buntil close\b", re.I
)


def mentions_in_person(text: str) -> bool:
    return bool(_IN_PERSON.search(text))


def mentions_time(text: str) -> bool:
    return bool(_TIME_WORDS.search(text))


@dataclass
class RuleFields:
    start_date: date
    end_date: date
    date_explicit: bool
    time_window: str | None
    dine_in_only: bool
    id_required: bool
    participating_only: bool
    is_free: bool
    eligibility: list[str] = field(default_factory=list)
    region_note: str | None = None
    likely_online: bool = False
    stale_wording: bool = False


def region_note(brand: str, text: str) -> str | None:
    paren = re.search(r"\(([^)]+)\)", brand)
    places = list(dict.fromkeys(_REGION.findall(text)))
    if paren:
        places.insert(0, paren[1])
    return "Only mentioned for: " + ", ".join(places) if places else None


def rule_fields(brand: str, text: str, target: date = VETERANS_DAY) -> RuleFields:
    start, end, explicit = parse_dates(text, target)
    elig = [k for k, rx in _ELIGIBILITY.items() if rx.search(text)]
    return RuleFields(
        start_date=start,
        end_date=end,
        date_explicit=explicit,
        time_window=parse_time_window(text),
        dine_in_only=bool(_DINE_IN.search(text)),
        id_required=bool(_ID.search(text)),
        participating_only=bool(_PARTICIPATING.search(text)),
        is_free=bool(_FREE.search(text)) and not _NEEDS_PURCHASE.search(text),
        eligibility=elig,
        region_note=region_note(brand, text),
        likely_online=bool(_ONLINE.search(text)) and not _IN_PERSON.search(text),
        stale_wording=bool(_LAST_YEAR.search(text)) and not explicit,
    )


# ---------- category ----------

_FOOD = re.compile(
    r"breakfast|lunch|dinner|\bmeal|coffee|fountain drink|\bsub\b|sandwich|burger|pizza"
    r"|entr[ée]e|taco|burrito|buffet|donut|smoothie|\bdrink\b|appetizer|dessert|wings",
    re.I,
)
_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "Car Care",
        re.compile(r"car wash|oil change|\bauto(?:motive|mobile)?\b|\btires?\b|detailing", re.I),
    ),
    ("Personal Care", re.compile(r"haircut|salon|barber|chiropract|massage|\bspa\b", re.I)),
    (
        "Attractions & Recreation",
        re.compile(r"admission|museum|\bzoo\b|aquarium|\bpark\b|cruise|ticket|game ?play", re.I),
    ),
]


def classify_category(brand: str, text: str, hint: str | None) -> str:
    """Section heading first; keyword rules for mixed lists (Military.com)."""
    if hint:
        return hint
    if _FOOD.search(text):
        return "Food & Drink"
    for category, rx in _CATEGORY_RULES:
        if rx.search(f"{brand} {text}"):
            return category
    if _ONLINE.search(text) and not _IN_PERSON.search(text):
        return "Online/Other"
    return "Retail & Grocery"


# ---------- meal slots ----------

_COFFEE_SNACK = re.compile(
    r"coffee|\bdrinks?\b|lemonade|smoothie|donut|doughnut|yogurt|custard|\btea\b|beverage"
    r"|pizookie|dessert|cookie|energy|beer|chips|queso|soda|latte|espresso|shake\b",
    re.I,
)
_MEAL = re.compile(
    r"\bmeal|entr[ée]e|burger|sandwich|pizza|taco|burrito|bowl|wings|shrimp|buffet"
    r"|breakfast|lunch|dinner|combo|steak|\bsub\b|slice|spaghetti|pancake|grand slam|platter"
    r"|plate|chimichanga|hot dog|chili dog|french toast|biscuit|bagel|kolache|salad|chicken"
    r"|pork|brisket|gyro|appetizer|soup|pasta|fries|cheeseburger|smashburger|wrap",
    re.I,
)
_BREAKFAST = re.compile(
    r"breakfast|pancake|grand slam|french toast|biscuit|bagel|kolache|waffle|omelet"
    r"|hash brown",
    re.I,
)
_DINNER = re.compile(r"\bdinner|\bnight\b", re.I)
_LUNCH = re.compile(r"\blunch\b", re.I)

KNOWN_BRAND_SLOTS: dict[str, list[str]] = {
    "denny": ["breakfast"],
    "ihop": ["breakfast"],
    "cracker barrel": ["breakfast"],
    "perkin": ["breakfast"],
    "huddle house": ["breakfast"],
    "keke breakfast cafe": ["breakfast"],
    "golden corral": ["dinner"],
    "starbuck": ["coffee_snack"],
    "dunkin": ["coffee_snack"],
}


def strip_brand(brand: str, text: str) -> str:
    """Remove the brand name so 'Hot Dog on a Stick' doesn't read as a hot dog."""
    name = re.sub(r"\s*\([^)]*\)", "", brand).strip()
    return re.sub(re.escape(name), " ", text, flags=re.I) if name else text


def is_coffee_only(text: str) -> bool:
    return bool(_COFFEE_SNACK.search(text)) and not _MEAL.search(text)


def slots_from_window(window: str | None) -> list[str]:
    """Spec: ends <= 11:00 breakfast; ends <= 16:00 lunch; starts >= 16:00 dinner;
    all day lunch+dinner. A morning window that starts before 10 and ends by noon counts
    as breakfast too (e.g. Denny's 5 a.m.-12 p.m.)."""
    if window == "all day":
        return ["lunch", "dinner"]
    span = window_minutes(window)
    if span is None:
        return []
    start, end = span
    if end <= 11 * 60 or (start < 10 * 60 and end <= 12 * 60):
        return ["breakfast"]
    if start >= 16 * 60:
        return ["dinner"]
    if end <= 16 * 60:
        return ["lunch"]
    return ["lunch", "dinner"]


def slots_from_keywords(text: str) -> list[str]:
    if is_coffee_only(text):
        return ["coffee_snack"]
    if _BREAKFAST.search(text):
        return ["breakfast"]
    if _DINNER.search(text):
        return ["dinner"]
    if _LUNCH.search(text):
        return ["lunch"]
    return []


def meal_slots(
    category: str,
    key: str,
    text: str,
    window: str | None,
    llm_slots: list[str] | None = None,
    override: list[str] | None = None,
) -> list[str]:
    """Order: overrides > coffee-only rule > time window > known brand > keywords > LLM.

    From the LLM only "breakfast" is trusted; generic meals default to lunch + dinner."""
    if override:
        return override
    if category != "Food & Drink":
        return ["any_time"]
    if is_coffee_only(text):
        return ["coffee_snack"]
    return (
        slots_from_window(window)
        or KNOWN_BRAND_SLOTS.get(key, [])
        or slots_from_keywords(text)
        or [s for s in (llm_slots or []) if s == "breakfast"]
        or ["lunch", "dinner"]
    )
