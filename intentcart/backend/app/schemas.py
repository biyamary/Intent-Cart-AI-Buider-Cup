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


CategoryName = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=40)
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
SmallBusinessPreference = Literal["off", "prefer", "only"]
SellerLabel = Literal["verified_small_business", "independent", "marketplace", "brand", "unknown"]
DiscoveryStatus = Literal["idle", "searching", "ready", "no_results", "failed"]
MAX_CHECKLIST_ITEMS = 10


class LookBrief(Contract):
    occasion: Text
    description: str = Field(default="", max_length=2000)
    total_budget_minor: int = Field(gt=0, le=100_000_000, strict=True)
    currency: Literal["INR"] = "INR"
    event_date: str | None = Field(default=None, max_length=40)
    sizes: ShortText = ""
    colours: list[Text] = Field(default_factory=list, max_length=12)
    avoid_colours: list[Text] = Field(default_factory=list, max_length=12)
    platforms: list[Text] = Field(default_factory=list, max_length=12)
    delivery_city: ShortText = ""
    delivery_pin: str = Field(default="", pattern=r"^(\d{6})?$")
    small_business: SmallBusinessPreference = "prefer"


class PieceSpec(Contract):
    category: CategoryName
    target: str = Field(default="", max_length=300)


class LookAnalysis(Contract):
    summary: str = Field(default="", max_length=1200)
    occasion: str = Field(default="", max_length=200)
    palette: list[str] = Field(default_factory=list, max_length=12)
    style_tags: list[str] = Field(default_factory=list, max_length=12)
    pieces: list[PieceSpec] = Field(default_factory=list, max_length=MAX_CHECKLIST_ITEMS)


class CatalogProduct(Contract):
    id: str
    category: CategoryName
    title: str
    price_minor: int = Field(ge=0)
    currency: Literal["INR"] = "INR"
    retailer: str = "Sample catalog"
    url: str | None = None
    image_url: str | None = None
    colour: str = ""
    source: Literal["live", "seed", "user"] = "seed"
    price_fetched_at: str | None = None
    match_reason: str = "Sample option for testing the look board."
    # Live products: every field below comes from the fetched page, never the model.
    price_source: Literal["catalog", "page", "user"] = "catalog"
    verification: Literal["seed", "json_ld", "shopify", "open_graph", "user"] = "seed"
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0)
    seller_label: SellerLabel = "unknown"
    seller_note: str = ""
    style_score: int | None = Field(default=None, ge=0, le=100)


class Boutique(Contract):
    name: str
    url: str | None = None
    note: str = ""
    kind: Literal["local", "online"] = "local"


class ChecklistItem(Contract):
    id: str = Field(default_factory=new_id)
    category: CategoryName
    target: str = Field(default="", max_length=300)
    hints: list[str] = Field(default_factory=list, max_length=8)
    status: Literal["open", "locked", "owned", "removed"] = "open"
    budget_cap_minor: int = 0
    chosen_product: CatalogProduct | None = None
    candidates: list[CatalogProduct] = Field(default_factory=list)
    # Verified live products for this item; `candidates` is the budget-filtered shortlist.
    pool: list[CatalogProduct] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)
    discovery: DiscoveryStatus = "idle"
    discovery_note: str = ""
    boutiques: list[Boutique] = Field(default_factory=list, max_length=8)


class ChecklistChoice(Contract):
    category: CategoryName
    status: Literal["open", "owned", "removed"] = "open"
    target: str = Field(default="", max_length=300)


class ConfirmChecklist(Contract):
    confirmed: Literal[True]
    items: list[ChecklistChoice] = Field(min_length=1, max_length=MAX_CHECKLIST_ITEMS)

    @model_validator(mode="after")
    def unique_categories(self):
        if len({item.category for item in self.items}) != len(self.items):
            raise ValueError("Each checklist category must be unique.")
        if all(item.status == "removed" for item in self.items):
            raise ValueError("Keep at least one checklist category.")
        return self


class ItemAction(Contract):
    action: Literal["lock", "swap", "own", "remove", "reopen", "reject"]
    product_id: str | None = None


class AddItem(Contract):
    category: CategoryName
    target: str = Field(default="", max_length=300)


class AddProductLink(Contract):
    url: str = Field(min_length=8, max_length=2048)
    price_minor: int | None = Field(default=None, gt=0, le=100_000_000, strict=True)


class Alternatives(Contract):
    request: str = Field(default="", max_length=300)
    max_price_minor: int | None = Field(default=None, gt=0, le=100_000_000, strict=True)


class InspirationItem(Contract):
    id: str = Field(default_factory=new_id)
    kind: Literal["pinterest", "web"]
    url: str
    title: str = ""
    image_url: str | None = None
    source: str = ""


class ConceptImage(Contract):
    id: str = Field(default_factory=new_id)
    artifact: str
    kind: Literal["concept", "reference_edit", "final"]
    caption: str = ""
    created_at: str = Field(default_factory=now)


class Look(Contract):
    id: str = Field(default_factory=new_id)
    brief: LookBrief
    status: Literal["awaiting_checklist", "shopping", "assembled"] = "awaiting_checklist"
    items: list[ChecklistItem]
    total_spent_minor: int = 0
    remaining_budget_minor: int = 0
    styling_note: str = "Styling note placeholder."
    created_at: str = Field(default_factory=now)
    # Agent-driven looks are linked to one stylist conversation and use live discovery.
    mode: Literal["board", "agent"] = "board"
    session_id: str | None = None
    analysis: LookAnalysis | None = None
    references: list[str] = Field(default_factory=list, max_length=6)
    inspiration: list[InspirationItem] = Field(default_factory=list, max_length=12)
    concepts: list[ConceptImage] = Field(default_factory=list, max_length=12)
    revision: int = 0
    updated_at: str = Field(default_factory=now)
