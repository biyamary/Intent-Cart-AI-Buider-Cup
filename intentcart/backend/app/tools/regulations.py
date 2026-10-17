import json
import re
from pathlib import Path

from app.schemas import RegulatoryAlert


def lookup_regulations(ingredients: list[str], countries: list[str]) -> list[RegulatoryAlert]:
    """Only reviewed source-backed entries may produce a non-unknown status."""
    corpus = json.loads((Path(__file__).parents[1] / "data" / "regulations.json").read_text())
    alerts = []
    for ingredient in ingredients:
        additives = re.findall(r"\bE\s*[- ]?\s*(\d{3,4}[a-z]?)\b", ingredient, re.I)
        for code in dict.fromkeys("E" + x.upper() for x in additives):
            for country in dict.fromkeys(countries):
                entry = next(
                    (x for x in corpus if x["additive_id"] == code and x["country"] == country),
                    None,
                )
                reviewed = bool(
                    entry
                    and entry.get("reviewed_at")
                    and str(entry.get("source_url", "")).startswith("https://")
                )
                alerts.append(
                    RegulatoryAlert(
                        ingredient=code,
                        country=country,
                        **(
                            {k: entry[k] for k in ("status", "condition", "source_url")}
                            | {"verified": True}
                            if reviewed
                            else {}
                        ),
                    )
                )
    return alerts
