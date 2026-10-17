from app.agents.llm import build_agent
from app.agents.schemas import Explanation, ParsedBrief
from app.config import Settings


def create_brief_agent(settings: Settings):
    return build_agent("stylist_brief", "stylist_brief.md", ParsedBrief, settings)


def create_styling_agent(settings: Settings):
    return build_agent("stylist_note", "stylist_note.md", Explanation, settings, lite=True)
