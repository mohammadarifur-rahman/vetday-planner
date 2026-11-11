import pytest

from vetday.sources import SOURCES, bluestar, military_com, today_com, va_news


def by_brand(offers):
    return {o.brand: o for o in offers}


def test_va_news(fixture_html):
    offers = va_news.parse(fixture_html("va_news"))
    assert len(offers) == 65
    b = by_brand(offers)
    assert b["Denny’s"].category_hint == "Food & Drink"
    assert "Grand Slam" in b["Denny’s"].text
    assert b["Denny’s"].brand_url and b["Denny’s"].brand_url.startswith("http")
    assert b["Great Clips"].category_hint == "Personal Care"
    assert b["Mount Vernon"].category_hint == "Attractions & Recreation"
    assert b["Grace for Vets"].category_hint == "Car Care"
    assert b["Publix"].category_hint == "Retail & Grocery"
    # brand without a colon: "<a>Bubbakoo’s</a> is honoring Veterans ..."
    assert "Bubbakoo’s" in b
    # non-breaking hyphens are normalized
    assert "dine-in" in b["Bar Louie"].text


def test_bluestar(fixture_html):
    offers = bluestar.parse(fixture_html("bluestar"))
    assert len(offers) == 83
    b = by_brand(offers)
    assert all(o.category_hint == "Food & Drink" for o in offers)
    assert "Sunrise Pancake" in b["Cracker Barrel"].text
    assert not b["Wendy’s"].text.startswith("Wendy’s:")


def test_military_com(fixture_html):
    offers = military_com.parse(fixture_html("military_com"))
    assert len(offers) == 43
    b = by_brand(offers)
    assert b["ZIPS Car Wash"].category_hint is None  # mixed list, keywords decide
    assert "free car wash" in b["ZIPS Car Wash"].text
    assert "Great Clips" in b  # uses an en dash separator on the page
    assert not any(o.brand.lower().startswith("related") for o in offers)


def test_today_com(fixture_html):
    offers = today_com.parse(fixture_html("today_com"))
    assert len(offers) == 68
    b = by_brand(offers)
    # bullet lists under a heading are folded into that brand's text
    assert "unlimited gameplay" in b["Dave & Buster’s"].text
    assert b["Yogurtland"].text.startswith("Anyone")


@pytest.mark.parametrize("src", SOURCES, ids=lambda s: s.NAME)
def test_every_source_has_metadata(src, fixture_html):
    offers = src.parse(fixture_html(src.NAME))
    assert offers
    assert {o.source for o in offers} == {src.NAME}
    assert all(o.brand and o.text and o.source_url == src.URL for o in offers)


def test_parsers_tolerate_unrelated_html():
    for src in SOURCES:
        assert src.parse("<html><body><p>nothing here</p></body></html>") == []


def test_va_news_nested_paragraph_does_not_leak(fixture_html):
    vcs = [o for o in va_news.parse(fixture_html("va_news")) if "iPad" in o.text]
    assert vcs and "Walgreens" not in vcs[0].text and "Editor" not in vcs[0].text
