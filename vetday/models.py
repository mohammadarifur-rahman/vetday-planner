"""Pydantic models at the boundaries. Keep in sync with the Data model section of CLAUDE.md."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from vetday.sources.base import RawOffer

__all__ = ["RawOffer", "Offer", "OfferExtraction", "SourceRef", "MealSlot", "Eligibility"]

MealSlot = Literal["breakfast", "lunch", "dinner", "coffee_snack", "any_time"]
Eligibility = Literal["veterans", "active_duty", "families", "spouses", "first_responders"]
Category = Literal[
    "Food & Drink",
    "Retail & Grocery",
    "Personal Care",
    "Attractions & Recreation",
    "Car Care",
    "Online/Other",
]
CATEGORIES: list[str] = list(Category.__args__)
MEAL_SLOTS: list[str] = list(MealSlot.__args__)


class SourceRef(BaseModel):
    name: str
    url: str


class OfferExtraction(BaseModel):
    """The only fields the local LLM fills. Kept small on purpose for small models."""

    summary: str = Field(description="The offer in your own words, at most 20 words.")
    items: list[str] = Field(default_factory=list, description="Free or discounted items.")
    meal_slots: list[MealSlot] = Field(
        default_factory=list,
        description="Meals this fits. Coffee/drink/dessert-only deals are coffee_snack. "
        "Non-food deals are any_time.",
    )
    eligibility: list[Eligibility] = Field(default_factory=list)
    is_location_based: bool = Field(
        default=True, description="False only for online-only deals (codes, websites)."
    )
    time_window: str | None = Field(
        default=None, description='24h "HH:MM-HH:MM", "all day", or null if not stated.'
    )


class Offer(BaseModel):
    id: str
    brand: str
    brand_key: str
    category: Category
    subcategory: str | None = None
    summary: str
    details: str
    items: list[str] = Field(default_factory=list)
    meal_slots: list[MealSlot] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    date_stated: bool = True  # False when the source only said "Veterans Day"
    time_window: str | None = None
    dine_in_only: bool = False
    id_required: bool = False
    is_free: bool = False
    eligibility: list[Eligibility] = Field(default_factory=list)
    participating_only: bool = False
    region_note: str | None = None
    is_location_based: bool = True
    brand_url: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    needs_verification: bool = False
    extracted_by: Literal["llm", "rules"] = "rules"

    def is_active_on(self, day: date) -> bool:
        if self.start_date is None:
            return True
        return self.start_date <= day <= (self.end_date or self.start_date)
