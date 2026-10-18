import json
import re
from datetime import date
from pathlib import Path

from app.schemas import (
    DEFAULT_COUNTRIES,
    AllergyAlert,
    ConfirmIngredients,
    FoodReport,
    Profile,
    Scan,
)
from app.tools.ingredients import DATABASE, normalize_ingredients, normalized, split_ingredient_list
from app.tools.regulations import lookup_regulations

ALIASES = json.loads((Path(__file__).parents[1] / "data" / "allergens.json").read_text())


def split_label(text: str) -> tuple[list[str], list[str], list[str]]:
    """Simple text scaffold; retain compound ingredients for human confirmation."""
    parts = re.split(r"\b(may\s+contain|contains)\s*:?\s*", text, flags=re.IGNORECASE)
    ingredients_text = re.sub(r"^\s*ingredients\s*:\s*", "", parts[0], flags=re.IGNORECASE)
    sections: dict[str, list[str]] = {"contains": [], "may contain": []}
    for index in range(1, len(parts) - 1, 2):
        key = re.sub(r"\s+", " ", parts[index].lower())
        sections[key].extend(split_ingredients(parts[index + 1]))
    return split_ingredients(ingredients_text), sections["contains"], sections["may contain"]


def split_ingredients(text: str) -> list[str]:
    return split_ingredient_list(text)


def match_allergens(confirmed: ConfirmIngredients, profile: Profile) -> list[AllergyAlert]:
    alerts = []
    for allergy in dict.fromkeys(normalized(a) for a in profile.allergies):
        canonical = next((key for key, aliases in ALIASES.items() if allergy in aliases), allergy)
        aliases = ALIASES.get(canonical, [allergy])
        for kind, entries in [
            ("contains", confirmed.ingredients + confirmed.contains),
            ("may_contain", confirmed.may_contain),
        ]:
            for entry in dict.fromkeys(entries):
                if any(
                    re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", normalized(entry))
                    for alias in aliases
                ):
                    alerts.append(
                        AllergyAlert(allergen=allergy, matched_ingredient=entry, type=kind)
                    )
    return alerts


def build_report(scan: Scan, confirmed: ConfirmIngredients, profile: Profile) -> FoodReport:
    alerts = match_allergens(confirmed, profile)
    ingredients = normalize_ingredients(confirmed.ingredients)
    countries = (
        confirmed.countries
        or profile.food_countries
        or list(dict.fromkeys(DEFAULT_COUNTRIES + [profile.country]))
    )
    names = {ingredient.canonical for ingredient in ingredients}
    age_notes = []
    for entry in DATABASE:
        if entry["canonical"] not in names:
            continue
        for advisory in entry.get("age_advisories", []):
            if (
                profile.age_group in advisory["age_groups"]
                and advisory["country"] in countries
                and date.fromisoformat(advisory["reviewed_at"])
                <= date.today()
                < date.fromisoformat(advisory["review_after"])
            ):
                age_notes.append(
                    {
                        "age_group": profile.age_group,
                        "note": advisory["note"],
                        "source_url": entry["source_url"],
                    }
                )
    age_notes.append(
        {
            "age_group": profile.age_group,
            "note": "Age-specific suitability is unverified: exact age, serving quantities and product category are not established by this label review.",
        }
    )
    diet_conflicts = []
    # These are label/preference matches, not medical or certification conclusions.
    for diet in profile.diet:
        target = normalized(diet)
        excluded = {
            "vegan": ["milk", "egg"],
            "dairy-free": ["milk"],
            "dairy free": ["milk"],
            "egg-free": ["egg"],
            "egg free": ["egg"],
        }.get(target, [])
        for match in match_allergens(confirmed, Profile(allergies=excluded)):
            diet_conflicts.append(
                {
                    "diet": diet,
                    "ingredient": match.matched_ingredient,
                    "note": f"{match.type}: {match.allergen} label match against the {diet} preference; verify the packaging.",
                }
            )
        if not excluded:
            diet_conflicts.append(
                {
                    "diet": diet,
                    "ingredient": "",
                    "note": "Unverified: no reviewed rule for this dietary preference.",
                }
            )
    return FoodReport(
        product=scan.product,
        ingredients=ingredients,
        allergy_alerts=alerts,
        label_allergens=match_allergens(confirmed, Profile(allergies=list(ALIASES))),
        regulatory_alerts=lookup_regulations(ingredients, countries),
        diet_conflicts=diet_conflicts,
        age_notes=age_notes,
        profile_context=profile.model_dump(
            include={"age_group", "allergies", "diet", "country", "food_countries"}
        ),
        things_to_watch=[
            "Allergen and diet matching uses an incomplete alias dictionary. Missing matches do not rule out allergens or establish dietary suitability.",
            "Regulation statuses apply to the stated use and jurisdiction. A restricted ingredient does not by itself show that this product violates a rule.",
            "IARC classifies carcinogenic hazard evidence, not cancer risk at normal intake. Missing IARC data does not mean Group 3 or absence of hazard.",
            "Citation verification checks ingredient identity and quoted text, not legal interpretation or product compliance.",
            "Compare the confirmed text with the original label, including contains and may-contain statements.",
        ],
        summary=(
            f"Parsed {len(ingredients)} ingredients from the confirmed label. "
            + (
                f"Found {len(alerts)} possible label matches against your saved allergies."
                if profile.allergies
                else "No allergies are saved, so personal allergy matching was not performed."
            )
        ),
    )
