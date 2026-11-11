# Kickoff prompt — paste this into Claude Code (VS Code panel)

Read CLAUDE.md first. Build the VetDay Planner described there. Veterans Day is tomorrow
(Nov 11), so ship a working MVP fast, then improve. Work in the phases below and stop after
each phase with a short summary so I can check it.

Sources (one module each, use the `add-offer-source` skill for every one):
1. va_news      https://news.va.gov/150505/2026-veterans-day-discounts-free-meals-offers/
2. bluestar     https://bluestarfam.org/resources-perspectives/finance-benefits/veterans-day-free-meals-restaurant-deals/
3. military_com https://www.military.com/veterans-day/retailers-veterans-day-military-discounts.html
4. today_com    https://www.today.com/food/restaurants/veterans-day-food-deals-2026-free-offers-rcna605115

If any site blocks the request, tell me and I'll save the page from my browser into data/raw/.

## Phase 1 — data (MVP core)
- `uv init`, add deps, create the layout from CLAUDE.md, `.env.example`, `.gitignore`.
- `models.py` (pydantic Offer + RawOffer), `db.py` (SQLite schema).
- Parsers for all 4 sources with fixtures + tests. Start with va_news (best structured).
- `extract.py`: local Ollama via `langchain-ollama` `ChatOllama` + `with_structured_output(
  OfferExtraction, method="json_schema")`, one paragraph per call, rules first, LLM only for the
  fuzzy fields, retry once then rules-only fallback, cached by text hash. No cloud API keys.
  Add a `--no-llm` flag to `refresh` for a fast rules-only run.
- `classify.py` meal-slot rules + `merge.py` dedupe by brand_key with conflict tracking.
- `pipeline.py refresh` and `status`. Then run the `refresh-and-verify` skill.

## Phase 2 — app (MVP UI)
Streamlit app with a sidebar: ZIP code, radius (5/10/15/25 mi, default 15), date (default Nov 11),
eligibility (Veteran / active duty / family), toggles "free only" and "dine-in OK".
Tabs:
1. **Plan my day** — three columns Breakfast / Lunch / Dinner (+ a Coffee & snacks row).
   Each card: brand, our short summary, time window, dine-in/ID badges, a "Find near <ZIP>"
   Google Maps search link, source links, and a "verify with location" note.
   Let me pick one per slot; show the picked day as a simple timeline and a
   "copy plan as text" button.
2. **Browse by category** — Food & Drink, Retail & Grocery, Personal Care, Attractions,
   Car Care, Online/Other; searchable table with filters for meal slot and date.
3. **Data health** — counts per source, last refresh time, Ollama status, offers needing
   verification.

## Phase 3 — real distances (optional, after the MVP works)
`geo.py`: pgeocode ZIP → lat/lng; OpenStreetMap Overpass lookup by brand within the radius
(free, no key), fuzzy brand-name check, haversine filter, SQLite cache. Use Google Places
instead only if GOOGLE_MAPS_API_KEY is set. Then add a **Near me** tab sorted by distance
(st.map). VA Canteen offers → point to the nearest VA medical center instead.

## Phase 4 — polish (only if time allows)
Ranking within each meal slot (distance, then "fully free" over discount, then confirmed
over needs_verification), an `.ics` export of the chosen plan, and a README with setup steps.

Rules: follow CLAUDE.md. The app runs fully local with Ollama; ask me before adding any paid API.
Commit after each phase with a clear message.
