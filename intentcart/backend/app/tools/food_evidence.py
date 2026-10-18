"""Citation integrity checks, independent of the research model."""

from datetime import date

from app.agents.schemas import ResearchFinding
from app.tools.food_fetch import allowed_url, authority_url, fetch_food_evidence
from app.tools.ingredients import aliases_for, mentions, normalized


async def verify_finding(finding: ResearchFinding, fetch=fetch_food_evidence) -> dict | None:
    try:
        url = allowed_url(finding.url)
        for value in (finding.effective_from, finding.review_after):
            if value:
                date.fromisoformat(value)
        if finding.effective_from and date.fromisoformat(finding.effective_from) > date.today():
            return None  # Future rules must not masquerade as current status.
        if finding.review_after and date.fromisoformat(finding.review_after) <= date.today():
            return None
    except ValueError:
        return None
    if finding.kind == "regulation":
        if finding.status == "unverified" or not finding.condition.strip():
            return None
        if not authority_url(url, finding.country):
            return None
    elif not finding.purpose.strip() or finding.country is not None:
        return None
    quote = normalized(finding.quote_or_snippet)
    if len(quote) < 20 or not any(mentions(quote, a) for a in aliases_for(finding.ingredient)):
        return None
    page = await fetch(url)
    if not page.get("ok"):
        return None
    try:
        final_url = allowed_url(page["url"])
    except (KeyError, ValueError):
        return None
    if finding.kind == "regulation" and not authority_url(final_url, finding.country):
        return None
    if quote not in normalized(page.get("text", "")):
        return None
    # This verifies citation identity and quote presence, NOT semantic entailment.
    return finding.model_dump() | {"url": final_url, "verified": True}
