from pydantic import BaseModel, Field


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


class ParsedBrief(BaseModel):
    occasion: str
    style_tags: list[str]
    palette: list[str]
    suggested_categories: list[str]
    missing_information: list[str]
