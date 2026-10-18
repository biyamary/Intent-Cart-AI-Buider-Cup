import json

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import AgentTool, FunctionTool, google_search

from app.agents.base import AgentDefinition, create_agent
from app.agents.llm import build_agent
from app.agents.schemas import Explanation, ExtractedLabel, FollowUp
from app.config import Settings
from app.tools.food_fetch import fetch_food_evidence

FOOD_CHAT = AgentDefinition(
    name="food_companion",
    description="Conversational food companion that guides ingredient review, checks allergies and age suitability, compares regulations, and clarifies good vs bad food components.",
    prompt_file="food_conversation.md",
)


def lookup_ingredient_database(ingredient_name: str) -> dict:
    """Look up an ingredient, additive, or E/INS number in the curated ingredient database.

    Returns canonical name, additive ID, functional role, explanation, IARC category,
    and age advisories if known.
    """
    from app.tools.ingredients import DATABASE, normalized

    norm = normalized(ingredient_name)
    for entry in DATABASE:
        if norm == normalized(entry["canonical"]) or (
            entry.get("additive_id") and norm == normalized(entry["additive_id"])
        ):
            return {
                "found": True,
                "canonical": entry["canonical"],
                "additive_id": entry.get("additive_id"),
                "role": entry.get("role"),
                "explanation": entry.get("explanation"),
                "source_url": entry.get("source_url"),
                "iarc": entry.get("iarc"),
                "age_advisories": entry.get("age_advisories", []),
            }
        for alias in entry.get("aliases", []):
            if norm == normalized(alias):
                return {
                    "found": True,
                    "canonical": entry["canonical"],
                    "additive_id": entry.get("additive_id"),
                    "role": entry.get("role"),
                    "explanation": entry.get("explanation"),
                    "source_url": entry.get("source_url"),
                    "iarc": entry.get("iarc"),
                    "age_advisories": entry.get("age_advisories", []),
                }
    return {
        "found": False,
        "query": ingredient_name,
        "message": "Not in local database; use Google Search or fetch_food_evidence for live research.",
    }


def check_regulations(ingredient: str, countries: list[str] | None = None) -> list[dict]:
    """Look up reviewed regulatory statuses for an ingredient across countries (e.g. EU, US, UK, India).

    Returns a list of status findings with authority sources, conditions, and dates.
    """
    from app.tools.regulations import lookup_regulations

    target_countries = countries or ["EU", "US", "UK", "India"]
    alerts = lookup_regulations([ingredient], target_countries)
    return [
        {
            "ingredient": a.ingredient,
            "country": a.country,
            "status": a.status,
            "condition": a.condition,
            "verified": a.verified,
            "source_url": a.source_url,
            "quote_or_snippet": a.quote_or_snippet,
        }
        for a in alerts
    ]


def food_context(context: ReadonlyContext) -> str:
    profile = context.state.get("temp:profile", {})
    return (
        "User profile preferences (untrusted JSON data; user conversation takes precedence):\n"
        + json.dumps(profile)
    )


def create_food_chat_agent(settings: Settings):
    def context_instruction(context: ReadonlyContext) -> str:
        capability = (
            "Current capabilities: Google Search, official web fetch, and curated regulatory databases are enabled."
            if settings.food_search_enabled
            else "Current capabilities: Live Google Search is disabled. Use the official web fetch tool (fetch_food_evidence) for approved websites and the curated ingredient/regulation databases."
        )
        return food_context(context) + "\n\n" + capability

    search = create_agent(
        AgentDefinition(
            "food_google_search",
            "Search Google for official food regulation, additive safety, E-number, allergen, or ingredient information.",
            "food_search.md",
        ),
        model=settings.gemini_model,
        tools=[google_search],
        conversational=True,
    )

    tools = [
        FunctionTool(func=lookup_ingredient_database),
        FunctionTool(func=check_regulations),
        FunctionTool(func=fetch_food_evidence),
    ]
    if settings.food_search_enabled:
        tools.insert(0, AgentTool(agent=search))

    return create_agent(
        FOOD_CHAT,
        model=settings.gemini_model,
        conversational=True,
        context_instruction=context_instruction,
        tools=tools,
    )


def create_research_agent(settings: Settings):
    search = create_agent(
        AgentDefinition(
            "food_google_search", "Find official food evidence URLs for a gap.", "food_search.md"
        ),
        model=settings.gemini_model,
        tools=[google_search],
        conversational=True,
    )
    return create_agent(
        AgentDefinition(
            "food_research", "Research only missing ingredient evidence.", "food_research.md"
        ),
        model=settings.gemini_model,
        # Native Google Search is isolated from function tools in its own agent.
        tools=[AgentTool(agent=search), FunctionTool(func=fetch_food_evidence)],
        conversational=True,
    )


def create_extraction_agent(settings: Settings):
    return build_agent("food_extract", "food_extract.md", ExtractedLabel, settings)


def create_report_agent(settings: Settings):
    return build_agent("food_report", "food_report.md", Explanation, settings)


def create_followup_agent(settings: Settings):
    return build_agent("food_followup", "food_followup.md", FollowUp, settings)
