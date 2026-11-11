"""Blue Star Families: one restaurant list of <li><strong>Brand:</strong> text</li>."""

import re

from bs4 import BeautifulSoup

from vetday.sources.base import RawOffer, clean_text, fetch_html

NAME = "bluestar"
DISPLAY_NAME = "Blue Star Families"
URL = (
    "https://bluestarfam.org/resources-perspectives/finance-benefits/"
    "veterans-day-free-meals-restaurant-deals/"
)

_BRAND_COLON = re.compile(r"^(?P<brand>[^:]{2,90}?)\s*:\s*(?P<rest>.+)$")


def fetch(offline: bool = False) -> tuple[str, bool]:
    return fetch_html(NAME, URL, offline=offline)


def parse(html: str) -> list[RawOffer]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", class_="entry-content")
    if body is None:
        return []
    offers: list[RawOffer] = []
    for ul in body.find_all("ul", class_="wp-block-list"):
        for li in ul.find_all("li", recursive=False):
            text = re.sub(r"\s+([:,.;])", r"\1", clean_text(li.get_text(" ")))
            m = _BRAND_COLON.match(text)
            if not m:
                continue
            strong = li.find("strong")
            link = li.find("a")
            offers.append(
                RawOffer(
                    NAME,
                    DISPLAY_NAME,
                    URL,
                    m["brand"].strip(),
                    m["rest"].strip(),
                    "Food & Drink",
                    (link.get("href") if link and link is not strong else None),
                )
            )
    return offers
