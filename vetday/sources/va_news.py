"""VA News: <h2>Veterans Day discounts: <Category></h2> then <p><a>Brand</a>: text</p>."""

import copy
import re

from bs4 import BeautifulSoup, Tag

from vetday.sources.base import RawOffer, clean_text, fetch_html

NAME = "va_news"
DISPLAY_NAME = "VA News"
URL = "https://news.va.gov/150505/2026-veterans-day-discounts-free-meals-offers/"

_HEADING_PREFIX = "veterans day discounts:"
_CATEGORY_BY_HEADING = {
    "restaurants": "Food & Drink",
    "retail": "Retail & Grocery",
    "personal care": "Personal Care",
    "attractions": "Attractions & Recreation",
    "car care": "Car Care",
}
_BRAND_COLON = re.compile(r"^(?P<brand>[^:]{2,90}?)\s*:\s*(?P<rest>.+)$")


def fetch(offline: bool = False) -> tuple[str, bool]:
    return fetch_html(NAME, URL, offline=offline)


def _category(heading: str) -> str:
    label = heading.lower().removeprefix(_HEADING_PREFIX).strip()
    for key, category in _CATEGORY_BY_HEADING.items():
        if label.startswith(key):
            return category
    return "Online/Other"


def _own_text(p: Tag) -> str:
    """Text of this paragraph only; the page has unclosed <p> tags that nest the next offer."""
    clone = copy.copy(p)
    for nested in clone.find_all("p"):
        nested.decompose()
    text = clean_text(clone.get_text(" "))
    return re.sub(r"\[Editor:[^\]]*\]?", "", text).strip()


def _split_brand(p: Tag) -> tuple[str, str, str | None] | None:
    text = _own_text(p)
    text = re.sub(r"\s+([:,.;])", r"\1", text)
    link = p.find("a")
    url = link.get("href") if link else None
    if m := _BRAND_COLON.match(text):
        return m["brand"].strip(), m["rest"].strip(), url
    if link and text.startswith(clean_text(link.get_text(" "))):
        brand = clean_text(link.get_text(" "))
        return brand, text, url  # e.g. "Bubbakoo's is honoring Veterans ..."
    return None


def parse(html: str) -> list[RawOffer]:
    soup = BeautifulSoup(html, "html.parser")
    offers: list[RawOffer] = []
    category: str | None = None
    for el in soup.find_all(["h2", "p"]):
        if el.name == "h2":
            heading = clean_text(el.get_text(" "))
            on = heading.lower().startswith(_HEADING_PREFIX)
            category = _category(heading) if on else None
            continue
        if category is None or "wp-block-paragraph" not in (el.get("class") or []):
            continue
        if split := _split_brand(el):
            brand, text, url = split
            offers.append(RawOffer(NAME, DISPLAY_NAME, URL, brand, text, category, url))
    return offers
