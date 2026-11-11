"""TODAY: <h2 class="body-heading">Brand</h2> followed by <p class="body-graf"> and bullet lists."""

from bs4 import BeautifulSoup

from vetday.sources.base import RawOffer, clean_text, fetch_html

NAME = "today_com"
DISPLAY_NAME = "TODAY"
URL = "https://www.today.com/food/restaurants/veterans-day-food-deals-2026-free-offers-rcna605115"


def fetch(offline: bool = False) -> tuple[str, bool]:
    return fetch_html(NAME, URL, offline=offline)


def parse(html: str) -> list[RawOffer]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", class_="article-body__content")
    if body is None:
        return []
    groups: list[tuple[str, list[str], str | None]] = []
    for el in body.find_all(["h2", "p", "li"]):
        if el.name == "h2":
            groups.append((clean_text(el.get_text(" ")), [], None))
            continue
        if not groups:
            continue  # intro paragraphs
        brand, parts, url = groups[-1]
        text = clean_text(el.get_text(" "))
        if text:
            parts.append(text if el.name == "p" else f"- {text}")
        link = el.find("a")
        if url is None and link is not None:
            groups[-1] = (brand, parts, link.get("href"))
    return [
        RawOffer(NAME, DISPLAY_NAME, URL, brand, " ".join(parts), "Food & Drink", url)
        for brand, parts, url in groups
        if parts
    ]
