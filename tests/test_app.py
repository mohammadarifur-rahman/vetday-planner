"""Smoke test: the Streamlit app renders every tab against a small temp database."""

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from vetday import config, db
from vetday.models import Offer, SourceRef

DAY = date(2026, 11, 11)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "vetday.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    conn = db.connect(path)
    src = [SourceRef(name="VA News", url="https://news.va.gov")]
    offers = [
        Offer(
            id="denny",
            brand="Denny’s",
            brand_key="denny",
            category="Food & Drink",
            summary="Free Grand Slam, $0 with ID",
            details="",
            meal_slots=["breakfast"],
            start_date=DAY,
            end_date=DAY,
            time_window="05:00-12:00",
            is_free=True,
            dine_in_only=True,
            id_required=True,
            eligibility=["veterans"],
            sources=src,
        ),
        Offer(
            id="chili",
            brand="Chili’s",
            brand_key="chili",
            category="Food & Drink",
            summary="Free entrée",
            details="",
            meal_slots=["lunch", "dinner"],
            start_date=DAY,
            end_date=DAY,
            eligibility=["veterans"],
            sources=src,
            conflicts=["Hours: A says x; B says y"],
            needs_verification=True,
        ),
        Offer(
            id="clips",
            brand="Great Clips",
            brand_key="great clip",
            category="Personal Care",
            summary="Free haircut",
            details="",
            meal_slots=["any_time"],
            start_date=DAY,
            end_date=DAY,
            eligibility=["veterans"],
            sources=src,
        ),
    ]
    db.replace_offers(conn, offers)
    run = db.start_refresh(conn, "rules", None)
    db.record_source_run(conn, run, "va_news", "ok", 3)
    db.finish_refresh(conn, run, 3)
    return path


def test_app_renders(temp_db):
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Plan my day", "Browse by category", "Data health"]
    assert any("Denny’s" in m.value for m in at.markdown)


def test_pick_builds_plan(temp_db):
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    at.text_input(key="zip").input("32801").run()
    pick = next(b for b in at.button if b.key == "pick-breakfast-denny")
    pick.click().run()
    assert not at.exception
    plan = at.code[0].value
    assert "Denny’s" in plan and "near 32801" in plan
