import json
from datetime import date
from pathlib import Path

from app.schemas import Ingredient, RegulatoryAlert
from app.tools.food_fetch import authority_url
from app.tools.ingredients import normalize_ingredients

CORPUS = json.loads((Path(__file__).parents[1] / "data" / "regulations.json").read_text())


def lookup_regulations(
    ingredients: list[Ingredient] | list[str], countries: list[str], *, on_date: date | None = None
) -> list[RegulatoryAlert]:
    """Complete matrix; absent, stale or future entries always remain unverified."""
    today = on_date or date.today()
    if ingredients and isinstance(ingredients[0], str):
        ingredients = normalize_ingredients(ingredients)
    findings = []
    for ingredient in ingredients:
        for country in dict.fromkeys(countries):
            finding = RegulatoryAlert(ingredient=ingredient.canonical, country=country)
            entry = next(
                (
                    e
                    for e in CORPUS
                    if e["additive_id"] == ingredient.additive_id and e["country"] == country
                ),
                None,
            )
            if entry:
                try:
                    reviewed = date.fromisoformat(entry["reviewed_at"])
                    expires = date.fromisoformat(entry["review_after"])
                    effective = date.fromisoformat(
                        entry.get("effective_from", entry["reviewed_at"])
                    )
                    valid = reviewed <= today < expires and effective <= today
                    valid = valid and authority_url(entry["source_url"], country)
                except (ValueError, KeyError):
                    valid = False
                if valid:
                    finding = RegulatoryAlert(
                        ingredient=ingredient.canonical,
                        country=country,
                        verified=True,
                        verification="reviewed",
                        checked_at=entry["reviewed_at"],
                        **{
                            k: v
                            for k, v in entry.items()
                            if k
                            in {
                                "status",
                                "condition",
                                "source_url",
                                "quote_or_snippet",
                                "effective_from",
                                "review_after",
                            }
                        },
                    )
            findings.append(finding)
    return findings
