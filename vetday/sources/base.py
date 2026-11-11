"""Shared Source protocol, RawOffer record, and polite fetch-with-cache helper."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from vetday.config import RAW_DIR, USER_AGENT

log = logging.getLogger(__name__)

_DASHES = re.compile("[\u2010-\u2015\u2212]")


@dataclass(frozen=True)
class RawOffer:
    source: str  # module name, e.g. "va_news"
    source_name: str  # display name, e.g. "VA News"
    source_url: str  # the list page
    brand: str
    text: str  # the offer paragraph, whitespace/dash-normalized
    category_hint: str | None = None  # section heading mapped to a Category
    brand_url: str | None = None


class Source(Protocol):
    NAME: str
    DISPLAY_NAME: str
    URL: str

    def fetch(self, offline: bool = False) -> tuple[str, bool]: ...

    def parse(self, html: str) -> list[RawOffer]: ...


class FetchBlocked(RuntimeError):
    pass


def clean_text(text: str) -> str:
    text = _DASHES.sub("-", text.replace("\xa0", " ").replace("\u200b", ""))
    return re.sub(r"\s+", " ", text).strip()


def raw_path(name: str) -> Path:
    return RAW_DIR / f"{name}.html"


def fetch_html(name: str, url: str, *, offline: bool = False) -> tuple[str, bool]:
    """One GET per refresh; cache to data/raw/<name>.html. Never try to bypass a block:
    on 403/429/network error fall back to the cached (or manually saved) file.
    Returns (html, fresh) where fresh is False when the cached file was used."""
    path = raw_path(name)
    if not offline:
        try:
            resp = httpx.get(
                url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
            )
            if resp.status_code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(resp.text, encoding="utf-8")
                return resp.text, True
            log.warning("%s returned HTTP %s; using cached copy if present", name, resp.status_code)
        except httpx.HTTPError as exc:
            log.warning("%s fetch failed (%s); using cached copy if present", name, exc)
    if path.exists():
        return path.read_text(encoding="utf-8"), False
    raise FetchBlocked(
        f"{name}: no response and no cached file. Save the page from your browser to {path}"
    )
