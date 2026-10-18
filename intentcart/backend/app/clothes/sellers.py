"""Label who sells a product. Deterministic: the model never assigns these labels."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.clothes.pages import host_of

DATA = Path(__file__).parents[1] / "data"

# Stable ordering used both in search prompts and deterministic shortlists.
# A listing still needs a verified product-page price before it can be shown.
POPULAR_RETAILERS = (
    "myntra.com",
    "amazon.in",
    "ajio.com",
    "flipkart.com",
    "nykaafashion.com",
    "tatacliq.com",
    "shopsy.in",
    "meesho.com",
)


STORE_NAMES = {
    "myntra.com": "Myntra",
    "amazon.in": "Amazon.in",
    "ajio.com": "AJIO",
    "flipkart.com": "Flipkart",
    "nykaafashion.com": "Nykaa Fashion",
    "tatacliq.com": "Tata CLiQ",
    "shopsy.in": "Shopsy",
    "meesho.com": "Meesho",
}


def store_name(url: str) -> str | None:
    """Display name of a popular store, e.g. "Myntra" for a myntra.com page."""
    return STORE_NAMES.get(_matches(host_of(url), STORE_NAMES) or "")


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
    # An unknown own-domain store is independent, but it is not a verified
    # small business. Only reviewed registry entries receive that treatment.
    return label == "verified_small_business"


def popular_retailer_domains() -> list[str]:
    return list(POPULAR_RETAILERS)


def retailer_priority(url: str | None, label: str, preferred: list[str] | None = None) -> int:
    host = host_of(url or "")
    for name in preferred or []:
        token = name.lower().replace("https://", "").replace("www.", "").split("/")[0]
        if token and (token in host or host.split(".")[0] in token):
            return -10
    for index, domain in enumerate(POPULAR_RETAILERS):
        if host == domain or host.endswith("." + domain):
            return index
    return {
        "marketplace": 20,
        "brand": 30,
        "verified_small_business": 40,
        "independent": 50,
        "unknown": 60,
    }.get(label, 60)
