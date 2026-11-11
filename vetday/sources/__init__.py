"""Registry of offer sources. Order = merge priority (official VA source first)."""

from types import ModuleType

from vetday.sources import bluestar, military_com, today_com, va_news

SOURCES: list[ModuleType] = [va_news, military_com, today_com, bluestar]
SOURCE_PRIORITY: dict[str, int] = {m.NAME: i for i, m in enumerate(SOURCES)}
