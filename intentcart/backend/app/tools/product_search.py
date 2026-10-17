import json
from pathlib import Path

from app.schemas import CatalogProduct, Look
from app.tools.budget import allocate_budget


def seed_catalog() -> list[CatalogProduct]:
    entries = json.loads((Path(__file__).parents[1] / "data" / "seed_catalog.json").read_text())
    return [CatalogProduct.model_validate(entry) for entry in entries]


def refresh_candidates(look: Look) -> Look:
    allocate_budget(look)
    catalog = seed_catalog()
    for item in look.items:
        item.candidates = (
            [
                p
                for p in catalog
                if p.category == item.category and p.price_minor <= item.budget_cap_minor
            ]
            if item.status == "open"
            else []
        )
    return look


async def grounded_product_search(
    brief: dict, category: str, budget_cap_minor: int
) -> list[CatalogProduct]:
    """TODO: isolated ADK Google Search agent, validate URLs, prices and retrieval timestamps.

    Keep grounded search separate from schema-constrained agents. Normalize results
    into CatalogProduct, then apply the deterministic budget filter before returning.
    Never invent stock, ratings, price timestamps, retailer URLs or delivery estimates.
    """
    raise NotImplementedError("Live product discovery is a scaffold extension point.")
