import json
import re
from pathlib import Path

from app.schemas import AllergyAlert, ConfirmIngredients, FoodReport, Ingredient, Profile, Scan
from app.tools.regulations import lookup_regulations

ALIASES = json.loads((Path(__file__).parents[1] / "data" / "allergens.json").read_text())


def split_label(text: str) -> tuple[list[str], list[str], list[str]]:
    """Simple text scaffold; retain compound ingredients for human confirmation."""
    parts = re.split(r"\b(may\s+contain|contains)\s*:?\s*", text, flags=re.I)
    ingredients_text = re.sub(r"^\s*ingredients\s*:\s*", "", parts[0], flags=re.I)
    sections: dict[str, list[str]] = {"contains": [], "may contain": []}
    for index in range(1, len(parts) - 1, 2):
        key = re.sub(r"\s+", " ", parts[index].lower())
        sections[key].extend(split_ingredients(parts[index + 1]))
    return split_ingredients(ingredients_text), sections["contains"], sections["may contain"]


def split_ingredients(text: str) -> list[str]:
    # Do not split a parenthesized ingredient group at its internal commas.
    return [
        part.strip(" .;") for part in re.split(r"[,;\n](?![^()]*\))", text) if part.strip(" .;\n")
    ]


def match_allergens(confirmed: ConfirmIngredients, profile: Profile) -> list[AllergyAlert]:
    alerts = []
    for allergy in dict.fromkeys(a.strip().lower() for a in profile.allergies):
        canonical = next((key for key, aliases in ALIASES.items() if allergy in aliases), allergy)
        aliases = ALIASES.get(canonical, [allergy])
        for kind, entries in [
            ("contains", confirmed.ingredients + confirmed.contains),
            ("may_contain", confirmed.may_contain),
        ]:
            for entry in dict.fromkeys(entries):
                if any(
                    re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", entry, re.I)
                    for alias in aliases
                ):
                    alerts.append(
                        AllergyAlert(allergen=allergy, matched_ingredient=entry, type=kind)
                    )
    return alerts


def build_report(scan: Scan, confirmed: ConfirmIngredients, profile: Profile) -> FoodReport:
    alerts = match_allergens(confirmed, profile)
    return FoodReport(
        product=scan.product,
        ingredients=[Ingredient(raw=x, canonical=x.strip().lower()) for x in confirmed.ingredients],
        allergy_alerts=alerts,
        regulatory_alerts=lookup_regulations(confirmed.ingredients, confirmed.countries),
        things_to_watch=[
            "Demo matching uses a small, incomplete keyword dictionary; matches need review and missing matches do not rule out allergens.",
            "The regulation corpus, diet checks, age notes, and ingredient explanations are placeholders.",
            "Compare the confirmed text with the original label, including contains and may-contain statements.",
        ],
        summary=f"Reviewed {len(confirmed.ingredients)} confirmed ingredient entries. Found {len(alerts)} possible label matches against your saved allergies. No suitability conclusion is available.",
    )
