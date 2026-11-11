"""Military.com: <h2>2026 Veterans Day Retail Discounts</h2> then <p>Brand -- text</p>.

The list mixes food, car washes, haircuts and online deals, so no category hint is set;
classify.py picks the category from keywords."""

import re

from bs4 import BeautifulSoup

from vetday.sources.base import RawOffer, clean_text, fetch_html

NAME = "military_com"
DISPLAY_NAME = "Military.com"
URL = "https://www.military.com/veterans-day/retailers-veterans-day-military-discounts.html"

_BRAND_SEP = re.compile(r"^(?P<brand>.{2,90}?)\s+-{1,2}\s+(?P<rest>.+)$")


def fetch(offline: bool = False) -> tuple[str, bool]:
    return fetch_html(NAME, URL, offline=offline)


def parse(html: str) -> list[RawOffer]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", class_="content-block-regular")
    if body is None:
        return []
    offers: list[RawOffer] = []
    in_list = False
    for el in body.find_all(["h2", "p"]):
        if el.name == "h2":
            in_list = (
                "veterans day" in el.get_text().lower() and "discount" in el.get_text().lower()
            )
            continue
        if not in_list:
            continue
        text = clean_text(el.get_text(" "))
        m = _BRAND_SEP.match(text)
        if not m or m["brand"].lower().startswith("related"):
            continue
        link = el.find("a")
        offers.append(
            RawOffer(
                NAME,
                DISPLAY_NAME,
                URL,
                m["brand"].strip(),
                re.sub(r"\s+([,.;])", r"\1", m["rest"].strip()),
                None,
                link.get("href") if link else None,
            )
        )
    return offers
