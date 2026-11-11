"""Hand corrections from data/overrides.yaml. These win over every rule and the LLM."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from vetday.classify import brand_key
from vetday.config import OVERRIDES_PATH


class Overrides(BaseModel):
    brand_aliases: dict[str, str] = Field(default_factory=dict)  # brand_key -> canonical key
    display_names: dict[str, str] = Field(default_factory=dict)  # brand_key -> shown name
    meal_slots: dict[str, list[str]] = Field(default_factory=dict)
    categories: dict[str, str] = Field(default_factory=dict)
    time_windows: dict[str, str | None] = Field(default_factory=dict)  # null clears it
    location_based: dict[str, bool] = Field(default_factory=dict)
    exclusions: list[str] = Field(default_factory=list)


@lru_cache
def load_overrides(path: Path = OVERRIDES_PATH) -> Overrides:
    if not path.exists():
        return Overrides()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return normalize(Overrides.model_validate(data))


def normalize(ov: Overrides) -> Overrides:
    """Let overrides.yaml use brand names as written on the sites ("AAFES", "Denny's")."""

    def keyed(d: dict) -> dict:
        return {brand_key(k, aliases): v for k, v in d.items()}

    aliases = {brand_key(k): brand_key(v) for k, v in ov.brand_aliases.items()}
    return Overrides(
        brand_aliases=aliases,
        display_names=keyed(ov.display_names),
        meal_slots=keyed(ov.meal_slots),
        categories=keyed(ov.categories),
        time_windows=keyed(ov.time_windows),
        location_based=keyed(ov.location_based),
        exclusions=[brand_key(k, aliases) for k in ov.exclusions],
    )
