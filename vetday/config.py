"""Settings loaded from .env (all optional; the app works with no keys)."""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.getenv("VETDAY_DB", DATA_DIR / "vetday.db"))
OVERRIDES_PATH = DATA_DIR / "overrides.yaml"

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY") or None

YEAR = 2026
VETERANS_DAY = date(YEAR, 11, 11)

USER_AGENT = (
    "VetDayPlanner/0.1 (personal, non-commercial Veterans Day planner; "
    "one request per source per refresh)"
)
