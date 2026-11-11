"""RawOffer -> Offer. Rules fill what they can; a local Ollama model fills only the fuzzy
fields in OfferExtraction, one paragraph per call, cached by text hash."""

import hashlib
import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Literal, Protocol

import httpx

from vetday import db
from vetday.classify import (
    brand_key,
    classify_category,
    meal_slots,
    mentions_in_person,
    mentions_time,
    rule_fields,
    strip_brand,
)
from vetday.config import OLLAMA_HOST, OLLAMA_MODEL
from vetday.models import Offer, OfferExtraction, RawOffer, SourceRef
from vetday.overrides import Overrides

log = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
LLM_TIMEOUT_S = 60  # wall-clock budget per paragraph, retries included
NUM_PREDICT = 512
ExtractStatus = Literal["cached", "llm", "fallback", "timeout"]
SYSTEM_PROMPT = """You normalize ONE Veterans Day offer from a public list.
Return only the requested fields.
- summary: the offer in your own words, at most 20 words. Mention what is free or discounted.
  Do not copy sentences from the text. Do not include the brand name.
- items: the specific free/discounted items (short noun phrases).
- meal_slots: breakfast, lunch, dinner, coffee_snack, any_time. Coffee, drinks, desserts or
  snacks only -> coffee_snack. Non-food offers -> any_time. A general free meal -> lunch, dinner.
- eligibility: veterans, active_duty, families, spouses, first_responders (who qualifies).
- is_location_based: false ONLY if the deal is online-only (website, promo code, booking).
- time_window: 24h "HH:MM-HH:MM", "all day", or null if no hours are stated."""

_WINDOW_OK = re.compile(r"^(\d{2}:\d{2}|open)-(\d{2}:\d{2}|close)$|^all day$")


class StructuredLLM(Protocol):
    def invoke(self, messages: list[tuple[str, str]]) -> OfferExtraction: ...


def ollama_status(host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL) -> tuple[bool, str]:
    """Check Ollama is up and the model is pulled. Never raises."""
    try:
        resp = httpx.get(f"{host}/api/tags", timeout=3)
        resp.raise_for_status()
    except httpx.HTTPError:
        return False, f"Ollama is not reachable at {host}. Start it with: ollama serve"
    names = {m["name"] for m in resp.json().get("models", [])}
    wanted = model if ":" in model else f"{model}:latest"
    if wanted not in names:
        return False, f"Model {model} is not pulled. Run: ollama pull {model}"
    return True, f"Ollama OK ({model})"


def make_structured_llm(model: str = OLLAMA_MODEL, host: str = OLLAMA_HOST) -> StructuredLLM:
    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        model=model,
        base_url=host,
        temperature=0,
        reasoning=False,  # disable qwen3 "thinking" output
        num_predict=NUM_PREDICT,  # cap runaway generations
        client_kwargs={"timeout": LLM_TIMEOUT_S},
    )
    return llm.with_structured_output(OfferExtraction, method="json_schema")


def cache_key(model: str, brand: str, text: str) -> str:
    payload = f"{PROMPT_VERSION}\n{model}\n{brand}\n{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def _invoke_with_deadline(llm: StructuredLLM, messages: list, seconds: float) -> OfferExtraction:
    """Run llm.invoke in a worker thread so a hung call can't block the refresh."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(llm.invoke, messages).result(timeout=seconds)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def llm_extract(
    raw: RawOffer,
    llm: StructuredLLM,
    conn: sqlite3.Connection,
    model: str,
    timeout_s: float = LLM_TIMEOUT_S,
) -> tuple[OfferExtraction | None, ExtractStatus]:
    """Cached; one retry within a wall-clock budget. None means fall back to rules-only."""
    key = cache_key(model, raw.brand, raw.text)
    if cached := db.cache_get(conn, key):
        return OfferExtraction.model_validate(cached), "cached"
    messages = [("system", SYSTEM_PROMPT), ("human", f"Brand: {raw.brand}\nOffer: {raw.text}")]
    deadline = time.monotonic() + timeout_s
    for attempt in (1, 2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, "timeout"
        try:
            result = _invoke_with_deadline(llm, messages, remaining)
            if not isinstance(result, OfferExtraction):
                result = OfferExtraction.model_validate(result)
            if not result.summary.strip():
                raise ValueError("empty summary")
        except FutureTimeout:
            log.warning("LLM timed out after %ss for %s", timeout_s, raw.brand)
            return None, "timeout"
        except Exception as exc:  # noqa: BLE001 - any model/parse error -> retry, then rules
            log.warning("LLM attempt %s failed for %s: %s", attempt, raw.brand, exc)
            continue
        db.cache_put(conn, key, model, result.model_dump())
        return result, "llm"
    return None, "fallback"


_ABBREV_END = re.compile(r"\b(?:Nov|Oct|Dec|St|oz|Jr|Mr|Mrs|Dr|U\.S|a\.m|p\.m|No|vs)\.$")
_LEAD_VERB = re.compile(
    r"^(?:is |are |will )?(?:also )?(?:giving|offering|offers|provides|gives|honoring|"
    r"running the following Veterans Day deals?:?)\s+",
    re.I,
)


def first_sentence(text: str) -> str:
    out = ""
    for part in re.split(r"(?<=[.;!?])\s+", text):
        out = f"{out} {part}".strip()
        if not _ABBREV_END.search(out):
            break
    return out.rstrip(".;")


def rules_summary(brand: str, text: str, max_words: int = 20) -> str:
    """Rules-only fallback: the brand-less first sentence, trimmed to max_words."""
    s = re.sub(rf"^{re.escape(brand)}\s*", "", text).lstrip(":- ").strip()
    s = _LEAD_VERB.sub("", first_sentence(s))
    s = s[:1].upper() + s[1:]
    return clip_words(s, max_words)


_CLAUSE_START = re.compile(r"^(?:in|on|at|for|from|with|to|during|through|until|and|or)$", re.I)


def clip_words(text: str, max_words: int = 20) -> str:
    """Trim to max_words, backing off to the last clause boundary so nothing ends mid-phrase."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    words = words[:max_words]
    for i in range(len(words) - 1, 7, -1):
        if _CLAUSE_START.match(words[i]) or words[i - 1].endswith((",", ";")):
            words = words[:i]
            break
    return " ".join(words).rstrip(",;:-") + "."


def offer_id(key: str, category: str) -> str:
    return f"{key.replace(' ', '-')}--{re.sub(r'[^a-z]+', '-', category.lower()).strip('-')}"


def build_offer(
    raw: RawOffer,
    ov: Overrides,
    extraction: OfferExtraction | None,
    *,
    llm_failed: bool = False,
) -> Offer:
    key = brand_key(raw.brand, ov.brand_aliases)
    rules = rule_fields(raw.brand, raw.text)
    category = ov.categories.get(key) or classify_category(raw.brand, raw.text, raw.category_hint)
    window = rules.time_window
    if window is None and extraction and extraction.time_window and mentions_time(raw.text):
        candidate = extraction.time_window.strip().lower()
        window = candidate if _WINDOW_OK.match(candidate) else None
    if key in ov.time_windows:
        window = ov.time_windows[key]
    if key in ov.location_based:
        location_based = ov.location_based[key]
    elif category == "Online/Other":
        location_based = False
    elif extraction is not None and not extraction.is_location_based:
        # small models over-report "online"; trust it only without in-person wording
        location_based = mentions_in_person(raw.text)
    else:
        location_based = not rules.likely_online
    return Offer(
        id=offer_id(key, category),
        brand=ov.display_names.get(key, raw.brand),
        brand_key=key,
        category=category,
        summary=clip_words(extraction.summary)
        if extraction
        else rules_summary(raw.brand, raw.text),
        details=raw.text,
        items=extraction.items if extraction else [],
        meal_slots=meal_slots(
            category,
            key,
            strip_brand(raw.brand, raw.text),
            window,
            extraction.meal_slots if extraction else None,
            ov.meal_slots.get(key),
        ),
        start_date=rules.start_date,
        end_date=rules.end_date,
        date_stated=rules.date_explicit,
        time_window=window,
        dine_in_only=rules.dine_in_only,
        id_required=rules.id_required,
        is_free=rules.is_free,
        eligibility=sorted(
            set(rules.eligibility or (extraction.eligibility if extraction else []) or ["veterans"])
        ),
        participating_only=rules.participating_only,
        region_note=rules.region_note,
        is_location_based=location_based,
        brand_url=raw.brand_url,
        sources=[SourceRef(name=raw.source_name, url=raw.source_url)],
        needs_verification=llm_failed or rules.stale_wording,
        extracted_by="llm" if extraction else "rules",
    )
