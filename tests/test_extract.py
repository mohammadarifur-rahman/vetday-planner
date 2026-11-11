import time

from vetday import db
from vetday.extract import build_offer, cache_key, llm_extract, rules_summary
from vetday.models import OfferExtraction, RawOffer
from vetday.overrides import Overrides

RAW = RawOffer(
    "va_news",
    "VA News",
    "https://news.va.gov/x",
    "Denny’s",
    "Offers Veterans and active duty a free Original Grand Slam on Nov. 11, 2026, "
    "5 a.m. to 12 p.m.; dine-in only and ID required.",
    "Food & Drink",
    "https://dennys.com",
)
GOOD = OfferExtraction(
    summary="Free Original Grand Slam breakfast for veterans and active duty, dine-in.",
    items=["Original Grand Slam"],
    meal_slots=["breakfast"],
    eligibility=["veterans", "active_duty"],
    is_location_based=True,
    time_window=None,
)


class FakeLLM:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_llm_success_is_cached():
    conn = db.connect(":memory:")
    llm = FakeLLM([GOOD])
    assert llm_extract(RAW, llm, conn, "m") == (GOOD, "llm")
    assert llm_extract(RAW, llm, conn, "m") == (GOOD, "cached")
    assert llm.calls == 1
    assert db.cache_get(conn, cache_key("m", RAW.brand, RAW.text))


def test_llm_retries_once_then_gives_up():
    conn = db.connect(":memory:")
    llm = FakeLLM([ValueError("bad json"), GOOD])
    assert llm_extract(RAW, llm, conn, "m") == (GOOD, "llm")
    llm = FakeLLM([ValueError("bad"), ValueError("still bad"), GOOD])
    other = RawOffer("va_news", "VA News", "u", "Denny’s", "other text")
    assert llm_extract(other, llm, conn, "m") == (None, "fallback")
    assert llm.calls == 2


class HangingLLM:
    def invoke(self, messages):
        time.sleep(2)
        return GOOD


def test_llm_timeout_falls_back_without_waiting():
    conn = db.connect(":memory:")
    t0 = time.monotonic()
    assert llm_extract(RAW, HangingLLM(), conn, "m", timeout_s=0.2) == (None, "timeout")
    assert time.monotonic() - t0 < 1


def test_build_offer_with_llm():
    o = build_offer(RAW, Overrides(), GOOD)
    assert o.brand_key == "denny"
    assert o.summary.startswith("Free Original Grand Slam")
    assert o.time_window == "05:00-12:00"  # regex beats the LLM
    assert o.meal_slots == ["breakfast"]
    assert o.dine_in_only and o.id_required and o.is_free
    assert not o.needs_verification and o.extracted_by == "llm"
    assert o.sources[0].name == "VA News"


def test_build_offer_rules_fallback_flags_verification():
    o = build_offer(RAW, Overrides(), None, llm_failed=True)
    assert o.needs_verification and o.extracted_by == "rules"
    assert len(o.summary.split()) <= 21


def test_llm_online_claim_ignored_for_in_store_text():
    online = GOOD.model_copy(update={"is_location_based": False, "time_window": "all day"})
    o = build_offer(
        RAW.__class__(
            "today_com",
            "TODAY",
            "u",
            "Applebee’s",
            "a free entrée while dining in at participating restaurants",
            "Food & Drink",
        ),
        Overrides(),
        online,
    )
    assert o.is_location_based
    assert o.time_window is None  # text never mentions hours


def test_overrides_win():
    ov = Overrides(
        display_names={"denny": "Denny's (override)"},
        meal_slots={"denny": ["lunch"]},
        categories={"denny": "Online/Other"},
        time_windows={"denny": None},
    )
    o = build_offer(RAW, ov, None)
    assert o.brand == "Denny's (override)"
    assert o.meal_slots == ["lunch"]
    assert o.category == "Online/Other" and not o.is_location_based
    assert o.time_window is None


def test_rules_summary_handles_abbreviations():
    s = rules_summary("Keke’s", "On Nov. 11 only, Keke’s offers veterans a free Classic Breakfast.")
    assert s.startswith("On Nov. 11 only")
    assert rules_summary("Baya Bar", "Baya Bar is giving veterans a free smoothie.") == (
        "Veterans a free smoothie"
    )


def test_cache_key_includes_model():
    # switching models (e.g. qwen3:1.7b -> qwen3:8b) must re-extract, not reuse old results
    assert cache_key("qwen3:1.7b", "Denny’s", "x") != cache_key("qwen3:8b", "Denny’s", "x")
    conn = db.connect(":memory:")
    llm = FakeLLM([GOOD, GOOD])
    assert llm_extract(RAW, llm, conn, "qwen3:1.7b")[1] == "llm"
    assert llm_extract(RAW, llm, conn, "qwen3:8b")[1] == "llm"
    assert llm.calls == 2


def test_clip_words_backs_off_to_clause_boundary():
    from vetday.extract import clip_words

    s = (
        "Veterans and active-duty service members get free Red, White, and Blueberry Pancake "
        "Combo from 7 a.m. to 7 p.m. on Nov. 11"
    )
    out = clip_words(s)
    assert len(out.split()) <= 20 and not out.endswith(("on.", "…"))
