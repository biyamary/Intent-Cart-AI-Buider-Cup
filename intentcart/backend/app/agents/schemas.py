from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import Country, RegulatoryStatus


class ExtractedLabel(BaseModel):
    product_name: str
    ingredients: list[str]
    contains: list[str] = Field(default_factory=list)
    may_contain: list[str] = Field(default_factory=list)
    needs_clearer_image: bool = False


class Explanation(BaseModel):
    summary: str


class FollowUp(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)


class ResearchFinding(BaseModel):
    ingredient: str = Field(max_length=200)
    kind: Literal["regulation", "purpose"] = "regulation"
    country: Country | None = None
    status: RegulatoryStatus = "unverified"
    condition: str = Field(default="", max_length=2000)
    purpose: str = Field(default="", max_length=300)
    quote_or_snippet: str = Field(default="", max_length=1200)
    url: str = Field(default="", max_length=2048)
    effective_from: str | None = Field(default=None, max_length=10)
    review_after: str | None = Field(default=None, max_length=10)


class ResearchResults(BaseModel):
    findings: list[ResearchFinding] = Field(default_factory=list, max_length=40)


class ParsedBrief(BaseModel):
    occasion: str
    style_tags: list[str]
    palette: list[str]
    suggested_categories: list[str]
    missing_information: list[str]


class CandidateScore(BaseModel):
    id: str = Field(max_length=40)
    score: int = Field(ge=0, le=100)
    reason: str = Field(default="", max_length=200)


class RankResult(BaseModel):
    scores: list[CandidateScore] = Field(default_factory=list, max_length=40)
