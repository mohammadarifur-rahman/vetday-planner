"""Location helpers. Default (no key, no lookups): Google Maps search links."""

from urllib.parse import quote_plus

from vetday.models import Offer

_VA_CANTEEN_KEYS = {"veteran canteen service", "veterans canteen service vc"}


def maps_search_url(query: str, zip_code: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(
        f"{query} near {zip_code}".strip()
    )


def offer_maps_url(offer: Offer, zip_code: str) -> str | None:
    """None for online-only offers. VA Canteen deals point to the nearest VA medical center."""
    if not offer.is_location_based:
        return None
    if offer.brand_key in _VA_CANTEEN_KEYS:
        return maps_search_url("VA medical center", zip_code)
    return maps_search_url(offer.brand, zip_code)
