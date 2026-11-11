# VetDay Planner

A local Streamlit app that collects Veterans Day offers (free meals, discounts, admissions)
from several public lists, organizes them by category and meal time, and finds participating
brands near a ZIP code so a Veteran can plan breakfast, lunch, dinner, and errands for the day.

Personal, non-commercial use. Every offer shows its source links and a
"verify participation with the location" note — never present an offer as guaranteed.

## Stack
- Python 3.12, managed with **uv** (Windows dev machine; use `uv run ...`, never bare `pip`)
- Streamlit (UI), pydantic v2 (schemas), httpx + beautifulsoup4 (scraping)
- LangChain + **`langchain-ollama`** (`ChatOllama`, local, no API key) for structured extraction.
  Model name comes from `.env` `OLLAMA_MODEL` (default `qwen3:8b`), host from `OLLAMA_HOST`
  (default `http://localhost:11434`). Use `temperature=0` and
  `.with_structured_output(OfferExtraction, method="json_schema")`.
- SQLite (`data/vetday.db`) via the stdlib `sqlite3` module, no ORM
- `pgeocode` for ZIP → lat/lng (offline)
- **Nearby, default (no key):** each location-based offer gets a Google Maps search link
  `https://www.google.com/maps/search/?api=1&query=<brand>+near+<zip>` (URL-encoded).
  Optional later: OSM Overpass for real distances; Google Places only if `GOOGLE_MAPS_API_KEY` is set.
- pytest for tests

## Commands
- Install: `uv sync`
- Refresh offers (scrape + extract + merge): `uv run python -m vetday.pipeline refresh`
- Run app: `uv run streamlit run app.py`
- Tests: `uv run pytest -q`
- Lint/format: `uv run ruff check . --fix && uv run ruff format .`

## Layout
```
app.py                     Streamlit entry point
vetday/
  sources/                 one module per source site, each exposing fetch() and parse()
    base.py                Source protocol + RawOffer dataclass
    va_news.py | bluestar.py | military_com.py | today_com.py
  extract.py               LLM extraction RawOffer -> Offer (structured output)
  classify.py              meal-slot + category rules (deterministic first, LLM second)
  merge.py                 dedupe across sources by normalized brand
  geo.py                   ZIP geocoding, Places lookup, haversine, cache
  planner.py               builds the breakfast/lunch/dinner plan
  db.py                    SQLite schema + queries
  pipeline.py              CLI: refresh / status
data/
  raw/                     cached HTML per source (manual fallback lives here too)
  overrides.yaml           hand corrections (brand aliases, meal slots, exclusions)
tests/fixtures/            saved HTML for parser tests
```

## Data model (keep in sync with `vetday/models.py`)
`Offer`: id, brand, brand_key (normalized), category, subcategory, summary (≤ 20 words, own words),
details, items, meal_slots (subset of breakfast|lunch|dinner|coffee_snack|any_time),
start_date, end_date, date_stated (false when the source only said "Veterans Day"),
time_window ("05:00-12:00", "open-16:00", "16:00-close", "all day", or null), dine_in_only,
id_required, is_free (free with no purchase needed), brand_url,
eligibility (veterans|active_duty|families|spouses|first_responders), participating_only,
region_note, is_location_based (false for online-only deals), sources: list[{name,url}],
conflicts: list[str], needs_verification: bool, extracted_by (llm|rules).

Categories: Food & Drink, Retail & Grocery, Personal Care, Attractions & Recreation,
Car Care, Online/Other.

## Rules
- **Scraping**: identify with a descriptive User-Agent, one request per source per refresh,
  cache HTML in `data/raw/`. If a site returns 403/blocked, do NOT try to bypass it —
  log it and read `data/raw/<source>.html` if the user saved it manually from their browser.
- **Parsers are per-site and deterministic** (BeautifulSoup). The LLM only normalizes
  one offer paragraph at a time. Don't send whole pages to the LLM.
- **Small local models need a small schema.** Code fills what rules can get (brand, source,
  category from the section heading, dates/times via regex, "dine-in"/"ID" keywords). The LLM
  fills only `OfferExtraction`: summary, items, meal_slots, eligibility, is_location_based,
  time_window (if regex missed it). Validate with pydantic; on failure retry once, then fall back
  to rules-only and set `needs_verification = true`. Cache results by paragraph text hash.
- Before a refresh, check Ollama is up (`GET {OLLAMA_HOST}/api/tags`) and the model is pulled;
  if not, print the exact `ollama pull <model>` command instead of crashing.
- Don't copy long passages from source sites into the UI. Show the short `summary`
  in our own words plus links back to each source.
- **Meal slots**: derive from time_window first (ends ≤ 11:00 → breakfast; ends ≤ 16:00 → lunch;
  starts ≥ 16:00 → dinner; "all day" → lunch+dinner), then known brand rules, then the LLM.
  Coffee-only deals → coffee_snack, not breakfast. `overrides.yaml` wins over everything.
- **Merging**: same brand_key from multiple sources → one Offer with all sources listed.
  If details disagree (date, item, hours), keep the official brand or VA source, record the
  difference in `conflicts`, and set `needs_verification = true`.
- **Geo**: only for `is_location_based` offers. Default is Maps search links (no lookups).
  If the optional Places/Overpass path is enabled: cache results in SQLite keyed by
  (brand_key, lat/lng rounded to 2 dp, radius), filter with haversine (default 15 mi), and
  fuzzy-check the place name matches the brand before keeping it.
- Config in `.env` (`OLLAMA_MODEL`, `OLLAMA_HOST`, optional `GOOGLE_MAPS_API_KEY`); never
  commit `.env` or print keys. The app must fully work with no keys at all.
- Keep functions small and typed; pydantic models at boundaries; no global state in Streamlit
  beyond `st.cache_data` / `st.session_state`.

## Definition of done for any change
Tests pass, `ruff` clean, `refresh` runs end to end, and the app loads with the current data.
