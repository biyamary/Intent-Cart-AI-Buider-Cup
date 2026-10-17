from app.agents.llm import build_agent
from app.agents.schemas import Explanation, ExtractedLabel, FollowUp
from app.config import Settings


def create_extraction_agent(settings: Settings):
    return build_agent("food_extract", "food_extract.md", ExtractedLabel, settings)


def create_report_agent(settings: Settings):
    return build_agent("food_report", "food_report.md", Explanation, settings)


def create_followup_agent(settings: Settings):
    return build_agent("food_followup", "food_followup.md", FollowUp, settings)
