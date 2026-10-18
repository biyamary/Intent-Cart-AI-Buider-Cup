import json
import re
import unicodedata
from pathlib import Path

from app.schemas import IarcClassification, Ingredient

DATABASE = json.loads((Path(__file__).parents[1] / "data" / "ingredients.json").read_text())
IARC_LABELS = {
    "1": "Carcinogenic to humans",
    "2A": "Probably carcinogenic to humans",
    "2B": "Possibly carcinogenic to humans",
    "3": "Not classifiable as to its carcinogenicity to humans",
}
CODE = re.compile(r"\b(e|ins)(\d{3,4}[a-z]?(?:\([ivx]+\))?)(?!\w)")
FUNCTION = re.compile(
    r"^(raising agents?|leavening agents?|emulsifiers?|humectants?|preservatives?|"
    r"stabili[sz]ers?|acidity regulators?|antioxidants?|sweeteners?|colou?r(?:ing)?s?)\b"
)


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"\b(e|ins)\s*[- ]?\s*(\d{3,4}[a-z]?)\b", r"\1\2", text)
    text = re.sub(r"\b((?:e|ins)\d{3,4}[a-z]?)\s*\(\s*([ivx]+)\s*\)", r"\1(\2)", text)
    return re.sub(r"\s+", " ", text).strip()


def mentions(text: str, alias: str) -> bool:
    alias = normalized(alias)
    # E503 must not silently stand in for the more specific E503(ii).
    suffix = r"(?!\s*\([ivx]+\))" if CODE.fullmatch(alias) and "(" not in alias else ""
    return bool(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)" + suffix, normalized(text)))


def aliases_for(ingredient: str) -> list[str]:
    entry = next((e for e in DATABASE if e["canonical"] == ingredient), None)
    if entry:
        return entry["aliases"]
    code = CODE.fullmatch(normalized(ingredient))
    return [ingredient, "E" + code[2], "INS" + code[2]] if code else [ingredient]


def split_ingredient_list(text: str) -> list[str]:
    """Split at top level only, preserving nested constituents and INS suffixes."""
    parts, stack, start = [], [], 0
    for index, char in enumerate(text):
        if char in "([":
            stack.append(char)
        elif char in ")]" and stack and stack[-1] == ("(" if char == ")" else "["):
            stack.pop()
        elif not stack and char in ",;\n":
            # Chemical locants (propane-1,2-diol) and decimal commas are not separators.
            if (
                char == ","
                and index > 0
                and text[index - 1].isdigit()
                and text[index + 1 : index + 2].isdigit()
            ):
                continue
            parts.append(text[start:index].strip(" .;"))
            start = index + 1
    parts.append(text[start:].strip(" .;"))
    return [part for part in parts if part]


def constituents(text: str, role: str | None = None):
    """Expand ingredient lists, keeping single annotations and code subtypes intact."""
    text = re.sub(
        r"(?<=[)\]])\s+and\s+(?=(?:humectant|emulsifier|raising agent|preservative))",
        ", ",
        text,
        flags=re.IGNORECASE,
    )
    for part in split_ingredient_list(text):
        part = normalized(part).strip(" .:")
        part = re.sub(r"[([]\s*\d+(?:[.,]\d+)?\s*%\s*[)\]]", "", part).strip()
        part = re.sub(r"\s+\d+(?:[.,]\d+)?\s*%$", "", part).strip()
        if not part or re.fullmatch(r"[\d.,\s%]+", part):
            continue
        function = FUNCTION.match(part)
        if function:
            rest = part[function.end() :].strip(" :")
            if rest:
                if rest[0] in "([" and rest[-1] == (")" if rest[0] == "(" else "]"):
                    rest = rest[1:-1]
                yield from constituents(rest, function[1].capitalize())
                continue
        # Expand compound lists, but not (maida), (from soyabean) or (ii).
        group = re.fullmatch(r"[^([]+[([](.*)[)\]]", part)
        if group and len(split_ingredient_list(group[1])) > 1:
            yield from constituents(group[1], role)
        else:
            yield part, role


def normalize_ingredients(raw_entries: list[str]) -> list[Ingredient]:
    result = {}
    for raw in raw_entries:
        for part, label_role in constituents(raw):
            matches = [
                e
                for e in DATABASE
                if any(
                    part == normalized(a) if e.get("exact_match") else mentions(part, a)
                    for a in e["aliases"]
                )
            ]
            if not matches:
                code = CODE.fullmatch(part)
                item = Ingredient(
                    raw=raw,
                    canonical=part,
                    additive_id=code[1].upper() + code[2] if code else None,
                )
                if label_role:
                    item.role = label_role
                    item.explanation = (
                        "Function stated on the confirmed label; not independently verified."
                    )
                    item.purpose_basis = "label"
                result.setdefault(part, item)
            for entry in matches:
                iarc = entry.get("iarc")
                result.setdefault(
                    entry["canonical"],
                    Ingredient(
                        raw=raw,
                        canonical=entry["canonical"],
                        additive_id=entry.get("additive_id"),
                        role=entry["role"],
                        explanation=entry["explanation"],
                        source_url=entry.get("source_url"),
                        purpose_basis="reviewed" if entry.get("source_url") else "unverified",
                        iarc=IarcClassification(**iarc, label=IARC_LABELS[iarc["group"]])
                        if iarc
                        else None,
                    ),
                )
    return list(result.values())
