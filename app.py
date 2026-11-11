"""VetDay Planner - Streamlit UI. Run: uv run streamlit run app.py"""

import re

import pandas as pd
import streamlit as st

from vetday import config, db
from vetday.extract import ollama_status
from vetday.geo import offer_maps_url
from vetday.models import CATEGORIES, MEAL_SLOTS, Offer
from vetday.planner import (
    ELIGIBILITY_CHOICES,
    SLOTS,
    Filters,
    build_plan,
    by_slot,
    clock,
    errands,
    filter_offers,
    format_dates,
    format_window,
    plan_text,
)

st.set_page_config(page_title="VetDay Planner", page_icon="🇺🇸", layout="wide")

VERIFY_NOTE = "Offers vary by location. Verify participation with the location before you go."
CARDS_SHOWN = 5


# ---------- data ----------


def _db_mtime() -> float:
    path = config.DB_PATH
    return path.stat().st_mtime if path.exists() else 0.0


@st.cache_data(show_spinner=False)
def load_offers(_mtime: float) -> list[Offer]:
    return db.load_offers(db.connect(config.DB_PATH))


@st.cache_data(show_spinner=False)
def load_last_refresh(_mtime: float) -> dict | None:
    return db.last_refresh(db.connect(config.DB_PATH))


@st.cache_data(ttl=30, show_spinner=False)
def cached_ollama_status() -> tuple[bool, str]:
    return ollama_status()


# ---------- small helpers ----------


def md(text: str) -> str:
    """Escape Markdown/LaTeX so '$15 voucher' or '*' in offer text renders literally."""
    return re.sub(r"([\\$*_~`\[\]<>#|])", r"\\\1", text)


def badges(o: Offer) -> str:
    out = [f":blue-badge[{format_window(o.time_window)}]"]
    if o.is_free:
        out.append(":green-badge[Free]")
    if o.dine_in_only:
        out.append(":orange-badge[Dine-in only]")
    if o.id_required:
        out.append(":violet-badge[Bring ID]")
    if o.participating_only:
        out.append(":gray-badge[Participating locations]")
    if not o.is_location_based:
        out.append(":gray-badge[Online]")
    if o.needs_verification:
        out.append(":red-badge[Needs verification]")
    return " ".join(out)


def link_line(o: Offer, zip_code: str) -> str:
    parts = []
    if url := offer_maps_url(o, zip_code):
        where = "VA medical center" if "canteen" in o.brand_key else "near " + (zip_code or "me")
        parts.append(f"[📍 Find {md(where)}]({url})")
    parts += [f"[{md(s.name)}]({s.url})" for s in o.sources]
    if o.brand_url:
        parts.append(f"[Brand page]({o.brand_url})")
    return " · ".join(parts)


def pick(slot: str, offer_id: str | None) -> None:
    st.session_state.setdefault("picks", {})[slot] = offer_id


def offer_card(o: Offer, zip_code: str, slot: str | None = None) -> None:
    with st.container(border=True):
        st.markdown(f"**{md(o.brand)}**")
        st.markdown(md(o.summary))
        st.markdown(badges(o))
        if o.region_note:
            st.caption(md(o.region_note))
        st.markdown(link_line(o, zip_code))
        for c in o.conflicts:
            st.caption(f"⚠️ Sources disagree. {md(c)}")
        st.caption(VERIFY_NOTE)
        if slot:
            picked = st.session_state.get("picks", {}).get(slot) == o.id
            st.button(
                "✓ Picked" if picked else "Pick",
                key=f"pick-{slot}-{o.id}",
                type="primary" if picked else "secondary",
                on_click=pick,
                args=(slot, None if picked else o.id),
                width="stretch",
            )


def card_list(offers: list[Offer], zip_code: str, slot: str) -> None:
    if not offers:
        st.info("No matching offers. Try loosening the sidebar filters.")
        return
    for o in offers[:CARDS_SHOWN]:
        offer_card(o, zip_code, slot)
    if len(offers) > CARDS_SHOWN:
        with st.expander(f"{len(offers) - CARDS_SHOWN} more"):
            for o in offers[CARDS_SHOWN:]:
                offer_card(o, zip_code, slot)


# ---------- sidebar ----------


def sidebar() -> tuple[Filters, str, int]:
    sb = st.sidebar
    sb.header("Your day")
    zip_code = sb.text_input("ZIP code", max_chars=5, placeholder="e.g. 32801", key="zip").strip()
    if zip_code and not re.fullmatch(r"\d{5}", zip_code):
        sb.warning("Enter a 5-digit ZIP code.")
        zip_code = ""
    radius = sb.select_slider("Radius (miles)", options=[5, 10, 15, 25], value=15)
    sb.caption("Map links search near your ZIP. Exact distances come in a later version.")
    day = sb.date_input("Date", value=config.VETERANS_DAY)
    who = sb.radio("I am a…", list(ELIGIBILITY_CHOICES), horizontal=False)
    free_only = sb.toggle("Free only", value=False, help="Hide discounts and buy-one deals")
    dine_in_ok = sb.toggle("Dine-in OK", value=True, help="Off hides dine-in-only offers")
    return Filters(day=day, who=who, free_only=free_only, dine_in_ok=dine_in_ok), zip_code, radius


# ---------- tabs ----------


def plan_tab(offers: list[Offer], f: Filters, zip_code: str) -> None:
    slots = by_slot(offers)
    labels = dict(SLOTS)
    cols = st.columns(3)
    for col, slot in zip(cols, ["breakfast", "lunch", "dinner"], strict=True):
        with col:
            st.subheader(f"{labels[slot]} ({len(slots[slot])})")
            card_list(slots[slot], zip_code, slot)

    st.subheader(f"Coffee & snacks ({len(slots['coffee_snack'])})")
    snack_cols = st.columns(4)
    for i, o in enumerate(slots["coffee_snack"][: CARDS_SHOWN * 2]):
        with snack_cols[i % 4]:
            offer_card(o, zip_code, "coffee_snack")
    if len(slots["coffee_snack"]) > CARDS_SHOWN * 2:
        with st.expander(f"{len(slots['coffee_snack']) - CARDS_SHOWN * 2} more coffee & snacks"):
            for o in slots["coffee_snack"][CARDS_SHOWN * 2 :]:
                offer_card(o, zip_code, "coffee_snack")

    errand_offers = {o.id: o for o in errands(offers)}
    st.subheader("Errands & extras")
    chosen = st.multiselect(
        "Add haircuts, car washes, store discounts or free admissions",
        options=list(errand_offers),
        format_func=lambda i: f"{errand_offers[i].brand} ({errand_offers[i].category})",
        key="errands",
    )

    st.divider()
    timeline(offers, f, zip_code, [errand_offers[i] for i in chosen])


def timeline(offers: list[Offer], f: Filters, zip_code: str, errand_picks: list[Offer]) -> None:
    st.subheader("Your day")
    by_id = {o.id: o for o in offers}
    picks = {s: by_id.get(i) for s, i in st.session_state.get("picks", {}).items() if i}
    items = build_plan({s: o for s, o in picks.items() if o}, errand_picks)
    if not items:
        st.caption("Pick an offer for breakfast, lunch, dinner or coffee to build your day.")
        return
    for it in items:
        o = it.offer
        hhmm = f"~{clock(it.minutes)}"
        maps = offer_maps_url(o, zip_code)
        where = f" · [📍 Map]({maps})" if maps else ""
        st.markdown(
            f"**{hhmm}** · {it.label}: **{md(o.brand)}**: {md(o.summary)} "
            f"_({format_window(o.time_window)})_{where}"
        )
    st.markdown("**Copy plan as text.** Use the copy icon in the box's top-right corner.")
    st.code(plan_text(items, f.day, zip_code), language=None, wrap_lines=True)
    if st.button("Clear plan"):
        st.session_state["picks"] = {}
        st.session_state["errands"] = []
        st.rerun()


def browse_tab(all_offers: list[Offer], f: Filters, zip_code: str) -> None:
    counts = {c: sum(o.category == c for o in all_offers) for c in CATEGORIES}
    category = st.segmented_control(
        "Category",
        options=CATEGORIES,
        format_func=lambda c: f"{c} ({counts[c]})",
        default="Food & Drink",
    )
    c1, c2, c3 = st.columns([2, 2, 1])
    query = c1.text_input("Search", placeholder="brand or item, e.g. pancake")
    slots = c2.multiselect("Meal slot", MEAL_SLOTS)
    active_only = c3.toggle(f"Only {f.day:%b} {f.day.day}", value=True)

    rows = []
    for o in all_offers:
        if category and o.category != category:
            continue
        if active_only and not o.is_active_on(f.day):
            continue
        if slots and not set(slots) & set(o.meal_slots):
            continue
        hay = f"{o.brand} {o.summary} {' '.join(o.items)}".lower()
        if query and query.lower() not in hay:
            continue
        rows.append(
            {
                "Brand": o.brand,
                "Offer": o.summary,
                "Dates": format_dates(o),
                "Hours": format_window(o.time_window),
                "Meals": ", ".join(o.meal_slots),
                "Free": o.is_free,
                "Dine-in only": o.dine_in_only,
                "ID": o.id_required,
                "Verify": "⚠️" if o.needs_verification else "",
                "Map": offer_maps_url(o, zip_code),
                "Source": o.sources[0].url if o.sources else None,
                "# sources": len(o.sources),
            }
        )
    st.caption(f"{len(rows)} offers · {VERIFY_NOTE}")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Offer": st.column_config.TextColumn(width="large"),
            "Map": st.column_config.LinkColumn(display_text="📍 Find"),
            "Source": st.column_config.LinkColumn(display_text="Source"),
        },
    )


def health_tab(offers: list[Offer], last: dict | None) -> None:
    ok, msg = cached_ollama_status()
    (st.success if ok else st.warning)(msg)
    if last is None:
        st.warning("No refresh yet. Run `uv run python -m vetday.pipeline refresh`.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Offers", len(offers))
    c2.metric("Confirmed by 2+ sources", sum(len(o.sources) > 1 for o in offers))
    c3.metric("Need verification", sum(o.needs_verification for o in offers))
    c4.metric("Extracted by LLM", sum(o.extracted_by == "llm" for o in offers))
    st.caption(
        f"Last refresh: {last['finished_at']} UTC · mode **{last['mode']}**"
        + (f" · model `{last['model']}`" if last["model"] else "")
    )
    st.dataframe(
        pd.DataFrame(last["sources"]).rename(
            columns={
                "source": "Source",
                "status": "Fetch",
                "raw_count": "Offers parsed",
                "message": "Note",
            }
        ),
        hide_index=True,
    )
    st.caption("Fetch `cached` means the saved copy in data/raw/ was used.")
    flagged = [o for o in offers if o.needs_verification]
    st.subheader(f"Needs verification ({len(flagged)})")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Brand": o.brand,
                    "Why": "; ".join(o.conflicts)
                    or (
                        "LLM fallback (rules only)" if o.extracted_by == "rules" else "Old wording"
                    ),
                    "Sources": ", ".join(s.name for s in o.sources),
                }
                for o in flagged
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    assumed = [o.brand for o in offers if not o.date_stated]
    if assumed:
        st.caption("Date assumed to be Nov 11 (source gave no date): " + ", ".join(assumed))
    st.code("uv run python -m vetday.pipeline refresh", language="bash")


# ---------- page ----------


def main() -> None:
    st.title("VetDay Planner")
    st.caption(
        "Veterans Day offers gathered from public lists, in our own short words, with links "
        "back to each source. Personal, non-commercial use. " + VERIFY_NOTE
    )
    mtime = _db_mtime()
    all_offers = load_offers(mtime)
    filters, zip_code, _radius = sidebar()
    if not all_offers:
        st.error("No offers yet. Run `uv run python -m vetday.pipeline refresh` first.")
        return
    offers = filter_offers(all_offers, filters)
    if not zip_code:
        st.info("Enter your ZIP code in the sidebar to make the map links search near you.")
    if filters.day != config.VETERANS_DAY:
        st.caption(f"Showing offers active on {filters.day:%b} {filters.day.day}.")
    plan, browse, health = st.tabs(["Plan my day", "Browse by category", "Data health"])
    with plan:
        plan_tab(offers, filters, zip_code)
    with browse:
        browse_tab(all_offers, filters, zip_code)
    with health:
        health_tab(all_offers, load_last_refresh(mtime))


main()
