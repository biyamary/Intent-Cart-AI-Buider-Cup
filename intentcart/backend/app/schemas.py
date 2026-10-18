"""Public API contracts. Monetary values are integer minor units (INR paise)."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Country = Literal["India", "EU", "US", "UK", "UAE", "Canada", "Australia/NZ", "Japan"]
RegulatoryStatus = Literal["banned", "restricted", "permitted", "unverified"]
DEFAULT_COUNTRIES = ["EU", "UK", "India", "US"]
Category = Literal[
    "outfit", "earrings", "necklace", "bangles", "footwear", "handbag", "hair accessories"
]


def new_id() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StyleProfile(Contract):
    sizes: dict[str, str] = Field(default_factory=dict)
    colours: list[Text] = Field(default_factory=list, max_length=20)
    budget_band: str = ""
    preferred_platforms: list[Text] = Field(default_factory=list, max_length=20)


class Profile(Contract):
    country: Country = "India"
    food_countries: list[Country] = Field(default_factory=list, max_length=8)
    age_group: Literal["unspecified", "child", "teen", "adult"] = "unspecified"
    allergies: list[Text] = Field(default_factory=list, max_length=30)
    diet: list[Text] = Field(default_factory=list, max_length=20)
    style: StyleProfile = Field(default_factory=StyleProfile)


class ExtractRequest(Contract):
    source: Literal["text", "barcode"] = "text"
    text: str = Field(default="", max_length=12000)
    barcode: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    product_name: Text = "Untitled product"

    @model_validator(mode="after")
    def require_input(self):
        if self.source == "text" and not self.text.strip():
            raise ValueError("Enter the ingredient label text.")
        if self.source == "barcode" and not self.barcode:
            raise ValueError("Enter an 8-14 digit barcode.")
        return self


class ProductLabel(Contract):
    name: str
    source: Literal["text", "barcode", "photo"]
    barcode: str | None = None
    source_url: str | None = None


class ConfirmIngredients(Contract):
    confirmed: Literal[True]
    ingredients: list[Text] = Field(min_length=1, max_length=200)
    contains: list[Text] = Field(default_factory=list, max_length=50)
    may_contain: list[Text] = Field(default_factory=list, max_length=50)
    countries: list[Country] | None = Field(default=None, min_length=1, max_length=8)


class AllergyAlert(Contract):
    allergen: str
    matched_ingredient: str
    type: Literal["contains", "may_contain"]


class RegulatoryAlert(Contract):
    ingredient: str
    country: Country
    status: RegulatoryStatus = "unverified"
    condition: str = "No reviewed regulation entry is available."
    source_url: str | None = None
    verified: bool = False
    verification: Literal["reviewed", "citation_verified", "unverified"] = "unverified"
    quote_or_snippet: str = ""
    checked_at: str | None = None
    effective_from: str | None = None
    review_after: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_unknown(cls, value):
        if isinstance(value, dict) and value.get("status") == "unknown":
            return value | {"status": "unverified"}
        return value


class IarcClassification(Contract):
    group: Literal["1", "2A", "2B", "3"]
    label: str
    source_url: str
    evaluated_year: int
    context: str
    reviewed_at: str


class Ingredient(Contract):
    raw: str
    canonical: str
    role: str = "Unverified"
    explanation: str = "No source-backed purpose is available."
    additive_id: str | None = None
    source_url: str | None = None
    purpose_basis: Literal["reviewed", "label", "citation_verified", "unverified"] = "unverified"
    iarc: IarcClassification | None = None


class ResearchCoverage(Contract):
    status: Literal["not_needed", "disabled", "completed", "partial", "unavailable"] = "not_needed"
    total_gaps: int = 0
    cache_hits: int = 0
    attempted: int = 0
    verified: int = 0
    deferred: int = 0
    failure_reason: str | None = None
    message: str = ""


class FoodReport(Contract):
    product: ProductLabel
    ingredients: list[Ingredient]
    allergy_alerts: list[AllergyAlert]
    label_allergens: list[AllergyAlert] = Field(default_factory=list)
    regulatory_alerts: list[RegulatoryAlert]
    diet_conflicts: list[dict[str, str]] = Field(default_factory=list)
    age_notes: list[dict[str, str]] = Field(default_factory=list)
    things_to_watch: list[str]
    summary: str
    profile_context: dict = Field(default_factory=dict)
    research: ResearchCoverage = Field(default_factory=ResearchCoverage)
    disclaimer: str = (
        "Not medical advice. An ingredient list alone cannot establish product compliance or "
        "individual suitability; quantities, food category and applicable dates matter."
    )
    generated_at: str = Field(default_factory=now)


class Scan(Contract):
    id: str = Field(default_factory=new_id)
    product: ProductLabel
    ingredients: list[str]
    contains: list[str] = Field(default_factory=list)
    may_contain: list[str] = Field(default_factory=list)
    status: Literal["awaiting_confirmation", "reported"] = "awaiting_confirmation"
    report: FoodReport | None = None
    created_at: str = Field(default_factory=now)


class Question(Contract):
    question: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class Answer(Contract):
    answer: str
    sources: list[str] = Field(default_factory=list)
    mode: Literal["demo", "gemini"]


class LookBrief(Contract):
    occasion: Text
    description: str = Field(default="", max_length=2000)
    total_budget_minor: int = Field(gt=0, le=100_000_000, strict=True)
    currency: Literal["INR"] = "INR"
    event_date: str | None = None


class CatalogProduct(Contract):
    id: str
    category: Category
    title: str
    price_minor: int = Field(ge=0)
    currency: Literal["INR"] = "INR"
    retailer: str = "Sample catalog"
    url: str | None = None
    image_url: str | None = None
    colour: str
    source: Literal["live", "seed"] = "seed"
    price_fetched_at: str | None = None
    match_reason: str = "Sample option for testing the look board."


class ChecklistItem(Contract):
    id: str = Field(default_factory=new_id)
    category: Category
    status: Literal["open", "locked", "owned", "removed"] = "open"
    budget_cap_minor: int = 0
    chosen_product: CatalogProduct | None = None
    candidates: list[CatalogProduct] = Field(default_factory=list)


class ChecklistChoice(Contract):
    category: Category
    status: Literal["open", "owned", "removed"] = "open"


class ConfirmChecklist(Contract):
    confirmed: Literal[True]
    items: list[ChecklistChoice] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def unique_categories(self):
        if len({item.category for item in self.items}) != len(self.items):
            raise ValueError("Each checklist category must be unique.")
        if all(item.status == "removed" for item in self.items):
            raise ValueError("Keep at least one checklist category.")
        return self


class ItemAction(Contract):
    action: Literal["lock", "swap", "own", "remove", "reopen"]
    product_id: str | None = None


class Look(Contract):
    id: str = Field(default_factory=new_id)
    brief: LookBrief
    status: Literal["awaiting_checklist", "shopping", "assembled"] = "awaiting_checklist"
    items: list[ChecklistItem]
    total_spent_minor: int = 0
    remaining_budget_minor: int = 0
    styling_note: str = "Styling note placeholder."
    created_at: str = Field(default_factory=now)
