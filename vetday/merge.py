"""Dedupe offers across sources by (brand_key, category), tracking disagreements."""

import re
import unicodedata
from collections import defaultdict
from datetime import date

from vetday.models import Offer
from vetday.sources import SOURCE_PRIORITY


def _priority(offer: Offer, source_names: dict[str, str]) -> int:
    name = offer.sources[0].name if offer.sources else ""
    return SOURCE_PRIORITY.get(source_names.get(name, ""), 99)


def _fmt_dates(o: Offer) -> str:
    def f(d: date | None) -> str:
        return f"{d:%b} {d.day}" if d else "?"  # %-d is not portable to Windows

    return f(o.start_date) if o.start_date == o.end_date else f"{f(o.start_date)}-{f(o.end_date)}"


_GENERIC = {
    "free",
    "full",
    "size",
    "full-size",
    "dine-in",
    "entree",
    "entrees",
    "meal",
    "meals",
    "off",
    "items",
    "item",
    "products",
    "discounted",
    "discount",
    "select",
    "special",
    "a",
    "an",
    "the",
    "and",
    "or",
    "with",
    "of",
    "menu",
    "complimentary",
    "lunch",
    "dinner",
}


def _item_words(items: list[str]) -> set[str]:
    text = unicodedata.normalize("NFKD", " ".join(items)).encode("ascii", "ignore").decode()
    words = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower().replace("'", "")))
    return {w.rstrip("s") for w in words - _GENERIC if not re.fullmatch(r"\d+%?", w)}


def _src(o: Offer) -> str:
    return o.sources[0].name


def merge_group(group: list[Offer]) -> Offer:
    """`group` is ordered by source priority; the first (VA when present) wins."""
    base = group[0]
    if len(group) == 1:
        return base
    conflicts: list[str] = []

    dated = [o for o in group if o.date_stated]
    date_ref = dated[0] if dated else base
    for o in dated[1:]:
        if (o.start_date, o.end_date) != (date_ref.start_date, date_ref.end_date):
            conflicts.append(
                f"Dates: {_src(date_ref)} says {_fmt_dates(date_ref)}; "
                f"{_src(o)} says {_fmt_dates(o)}"
            )

    timed = [o for o in group if o.time_window]
    window = timed[0].time_window if timed else None
    for o in timed[1:]:
        if o.time_window != window:
            conflicts.append(
                f"Hours: {_src(timed[0])} says {window}; {_src(o)} says {o.time_window}"
            )

    with_items = [o for o in group if o.items]
    if len(with_items) > 1:
        # Only specific items can disagree; "entrée" vs a menu list is not a conflict.
        ref_words = _item_words(with_items[0].items)
        for o in with_items[1:]:
            words = _item_words(o.items)
            if ref_words and words and not ref_words & words:
                conflicts.append(
                    f"Item: {_src(with_items[0])} says {', '.join(with_items[0].items)}; "
                    f"{_src(o)} says {', '.join(o.items)}"
                )

    sources = list({s.name: s for o in group for s in o.sources}.values())
    return base.model_copy(
        update={
            "start_date": date_ref.start_date,
            "end_date": date_ref.end_date,
            "date_stated": date_ref.date_stated,
            "time_window": window,
            "dine_in_only": any(o.dine_in_only for o in group),
            "id_required": any(o.id_required for o in group),
            "participating_only": any(o.participating_only for o in group),
            "eligibility": sorted({e for o in group for e in o.eligibility}),
            "brand_url": next((o.brand_url for o in group if o.brand_url), None),
            "sources": sources,
            "conflicts": conflicts,
            "needs_verification": bool(conflicts) or any(o.needs_verification for o in group),
        }
    )


def _clusters(group: list[Offer]) -> list[list[Offer]]:
    """Split one brand's offers so each cluster has at most one offer per source.
    (VA lists the Veterans Canteen Service twice: a meal deal and an iPad deal.)"""
    clusters: list[list[Offer]] = []
    for o in group:
        name = o.sources[0].name
        home = next(
            (
                c
                for c in clusters
                if name not in {x.sources[0].name for x in c} and c[0].category == o.category
            ),
            None,
        ) or next((c for c in clusters if name not in {x.sources[0].name for x in c}), None)
        if home is None:
            clusters.append([o])
        else:
            home.append(o)
    return clusters


def merge_offers(offers: list[Offer], source_names: dict[str, str]) -> list[Offer]:
    """Group by brand_key across sources (category comes from the preferred source).
    source_names maps display name -> module name (for priority lookup)."""
    groups: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        groups[o.brand_key].append(o)
    merged: list[Offer] = []
    seen_ids: set[str] = set()
    for group in groups.values():
        group.sort(key=lambda o: _priority(o, source_names))
        for cluster in _clusters(group):
            offer = merge_group(cluster)
            if offer.id in seen_ids:
                offer = offer.model_copy(update={"id": f"{offer.id}-{len(seen_ids)}"})
            seen_ids.add(offer.id)
            merged.append(offer)
    return sorted(merged, key=lambda o: (o.category, o.brand_key))
