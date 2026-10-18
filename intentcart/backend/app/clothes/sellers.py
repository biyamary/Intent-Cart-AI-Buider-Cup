"""Label who sells a product. Deterministic: the model never assigns these labels."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.clothes.pages import host_of

DATA = Path(__file__).parents[1] / "data"


@dataclass(frozen=True)
class Registry:
    marketplaces: frozenset[str]
    brands: frozenset[str]
    not_stores: frozenset[str]
    small_businesses: dict[str, dict]


def _matches(host: str, domains) -> str | None:
    return next((d for d in domains if host == d or host.endswith("." + d)), None)


@lru_cache
def registry() -> Registry:
    sellers = json.loads((DATA / "sellers.json").read_text(encoding="utf-8"))
    small = json.loads((DATA / "small_businesses.json").read_text(encoding="utf-8"))
    verified = {}
    for entry in small.get("businesses", []):
        # A verified badge needs a reviewed source; incomplete entries are ignored.
        if entry.get("domain") and entry.get("source_url") and entry.get("reviewed_at"):
            verified[entry["domain"].lower().removeprefix("www.")] = entry
    return Registry(
        marketplaces=frozenset(sellers["marketplaces"]),
        brands=frozenset(sellers["brands"]),
        not_stores=frozenset(sellers["not_stores"]),
        small_businesses=verified,
    )


def is_store_url(url: str) -> bool:
    host = host_of(url)
    return bool(host) and not _matches(host, registry().not_stores)


def classify(url: str) -> tuple[str, str]:
    """Return (seller_label, note) for a product URL."""
    host = host_of(url)
    reg = registry()
    if domain := _matches(host, reg.small_businesses):
        entry = reg.small_businesses[domain]
        where = f" in {entry['city']}" if entry.get("city") else ""
        return "verified_small_business", f"{entry['name']}{where}, reviewed {entry['reviewed_at']}"
    if _matches(host, reg.marketplaces):
        return "marketplace", "Marketplace listing; the individual seller is not verified."
    if _matches(host, reg.brands):
        return "brand", "Large brand or chain."
    if host:
        return "independent", "Sells from its own online store (not a marketplace or a chain we know of)."
    return "unknown", ""


def small_business_domains() -> list[str]:
    return sorted(registry().small_businesses)


def is_small_business(label: str) -> bool:
    return label in {"verified_small_business", "independent"}
