"""Deterministic, market-informed planning for a complete look.

The model never invents prices. Until product pages have been verified we use
conservative category bands; once verified pools exist, those observations
replace the fallback bands and reserve the cheapest complete basket.
"""

from statistics import median

from app.schemas import BudgetPlan, CatalogProduct, Look, PriceBand


# Public for the demo-board category gate and backwards compatibility.
WEIGHTS = {
    "outfit": 10,
    "top": 6,
    "shirt": 6,
    "blouse": 6,
    "kurta": 6,
    "bottom": 6,
    "pants": 6,
    "trousers": 6,
    "jeans": 6,
    "skirt": 6,
    "footwear": 5,
    "shoes": 5,
    "handbag": 4,
    "earrings": 2,
    "necklace": 3,
    "bangles": 2,
    "hair accessories": 1,
}

ROLE_ALIASES = {
    "outfit": {
        "outfit", "look", "dress", "gown", "lehenga", "lehenga set", "saree",
        "sari", "salwar suit", "suit set", "co-ord", "coord", "jumpsuit",
    },
    "top": {"top", "shirt", "t-shirt", "tshirt", "tee", "blouse", "kurta", "tunic"},
    "bottom": {
        "bottom", "bottoms", "pant", "pants", "trouser", "trousers", "jeans",
        "skirt", "shorts", "palazzo", "palazzos", "churidar", "salwar",
    },
    "outerwear": {"jacket", "blazer", "coat", "cardigan", "shrug"},
    "footwear": {"footwear", "shoe", "shoes", "heels", "sandals", "sneakers", "juttis", "flats"},
    "bag": {"bag", "handbag", "clutch", "potli", "purse", "tote"},
    "jewellery": {"earrings", "earring", "necklace", "bangles", "bracelet", "ring", "jewellery", "jewelry"},
    "layer": {"dupatta", "stole", "scarf", "shawl"},
    "accessory": {"hair accessories", "belt", "watch", "sunglasses", "accessory", "accessories"},
}

# low / typical / high INR paise. These are planning priors, never presented as
# verified store prices. They prevent a shirt or trousers being budgeted like a
# small accessory while the initial market survey is still running.
FALLBACK_BANDS = {
    "outfit": (120_000, 300_000, 800_000),
    "top": (50_000, 110_000, 240_000),
    "bottom": (65_000, 120_000, 250_000),
    "outerwear": (90_000, 180_000, 400_000),
    "footwear": (70_000, 130_000, 220_000),
    "bag": (55_000, 110_000, 250_000),
    "jewellery": (25_000, 70_000, 180_000),
    "layer": (35_000, 80_000, 180_000),
    "accessory": (20_000, 50_000, 120_000),
}

ROLE_WEIGHTS = {
    "outfit": 10,
    "top": 6,
    "bottom": 6,
    "outerwear": 7,
    "footwear": 5,
    "bag": 4,
    "jewellery": 3,
    "layer": 3,
    "accessory": 2,
}


def canonical_budget_role(category: str) -> str:
    key = " ".join(category.strip().lower().replace("_", " ").split())
    for role, aliases in ROLE_ALIASES.items():
        if key in aliases:
            return role
    # Handle useful descriptions such as "formal shirt" without allowing very
    # short aliases to match arbitrary words.
    words = set(key.replace("-", " ").split())
    for role, aliases in ROLE_ALIASES.items():
        if any(" " not in alias and len(alias) > 3 and alias in words for alias in aliases):
            return role
    return "accessory"


def weight(category: str) -> int:
    return ROLE_WEIGHTS[canonical_budget_role(category)]


def verified_for_planning(product: CatalogProduct) -> bool:
    """Only fetched product-page prices may support a budget guarantee."""
    return (
        product.source == "live"
        and product.price_source == "page"
        and product.verification in {"json_ld", "shopify", "open_graph"}
        and product.price_minor > 0
        and product.availability != "out_of_stock"
        and (product.style_score is None or product.style_score >= 35)
    )


def _market_products(item) -> list[CatalogProduct]:
    return sorted(
        (
            product
            for product in item.pool
            if product.id not in item.rejected_ids and verified_for_planning(product)
        ),
        key=lambda product: product.price_minor,
    )


def _band(item) -> tuple[PriceBand, list[CatalogProduct]]:
    products = _market_products(item)
    if products:
        prices = [product.price_minor for product in products]
        # The upper observed quartile avoids letting one luxury outlier consume
        # the entire plan while still showing a useful shopping range.
        high_index = min(len(prices) - 1, (3 * len(prices)) // 4)
        return PriceBand(
            low_minor=prices[0],
            typical_minor=int(median(prices)),
            high_minor=prices[high_index],
            sample_count=len(prices),
            source="market",
        ), products
    low, typical, high = FALLBACK_BANDS[canonical_budget_role(item.category)]
    return PriceBand(low_minor=low, typical_minor=typical, high_minor=high), []


def _shares(total: int, weights: list[int]) -> list[int]:
    """Largest-remainder split that preserves every paise."""
    if not weights or total <= 0:
        return [0] * len(weights)
    denominator = sum(weights)
    if denominator <= 0:
        weights, denominator = [1] * len(weights), len(weights)
    result = [total * value // denominator for value in weights]
    spare = total - sum(result)
    order = sorted(
        range(len(weights)),
        key=lambda index: (total * weights[index]) % denominator,
        reverse=True,
    )
    for index in order[:spare]:
        result[index] += 1
    return result


def _fund_towards(planned: list[int], remaining: int, targets: list[int]) -> int:
    needs = [max(0, target - current) for current, target in zip(planned, targets)]
    amount = min(remaining, sum(needs))
    if amount:
        portions = _shares(amount, needs)
        for index, portion in enumerate(portions):
            planned[index] += portion
    return remaining - amount


def allocate_budget(look: Look) -> Look:
    """Replan the full basket from selected prices and current market evidence.

    Every open cap is a safe reservation: choosing any displayed product within
    that cap leaves the other items' allocations intact. When every open item
    has a verified option, ``feasible`` and the reserved product ids describe a
    real complete basket rather than an estimate.
    """
    spent = sum(
        item.chosen_product.price_minor
        for item in look.items
        if item.status == "locked" and item.chosen_product
    )
    remaining = look.brief.total_budget_minor - spent
    if remaining < 0:
        raise ValueError("Selected products exceed the total budget.")

    open_items = [item for item in look.items if item.status == "open"]
    bands: list[PriceBand] = []
    markets: list[list[CatalogProduct]] = []
    for item in look.items:
        item.budget_role = canonical_budget_role(item.category)
        item.reserved_product_id = None
        if item.status == "locked" and item.chosen_product:
            price = item.chosen_product.price_minor
            item.price_band = PriceBand(
                low_minor=price, typical_minor=price, high_minor=price,
                sample_count=1, source="selected",
            )
            item.planned_budget_minor = item.budget_cap_minor = price
            item.survey_status = "not_needed"
        elif item.status != "open":
            item.planned_budget_minor = item.budget_cap_minor = 0
            item.survey_status = "not_needed"
        else:
            band, products = _band(item)
            item.price_band = band
            item.survey_status = (
                "ready" if products else
                "surveying" if item.discovery == "searching" else
                "no_verified_prices" if item.pool or item.discovery in {"ready", "no_results", "failed"} else
                "pending"
            )
            bands.append(band)
            markets.append(products)

    lows = [band.low_minor for band in bands]
    planned = [0] * len(open_items)
    if open_items:
        if remaining < sum(lows):
            planned = _shares(remaining, lows)
            unallocated = 0
        else:
            planned = list(lows)
            unallocated = remaining - sum(planned)
            unallocated = _fund_towards(
                planned, unallocated, [band.typical_minor for band in bands]
            )
            unallocated = _fund_towards(
                planned, unallocated, [band.high_minor for band in bands]
            )
            if unallocated:
                extra = _shares(
                    unallocated,
                    [ROLE_WEIGHTS[item.budget_role] for item in open_items],
                )
                planned = [value + extra[index] for index, value in enumerate(planned)]
        for item, amount in zip(open_items, planned):
            item.planned_budget_minor = item.budget_cap_minor = amount

    verified_count = sum(bool(products) for products in markets)
    all_verified = verified_count == len(open_items)
    minimum_total = spent + sum(band.low_minor for band in bands)
    feasible = minimum_total <= look.brief.total_budget_minor if all_verified else None
    if not open_items:
        feasible, status = True, "ready"
        note = "Every checklist item is resolved."
    elif all_verified and feasible:
        status = "ready"
        note = "A complete basket is reserved within budget using verified store prices."
        for item, products in zip(open_items, markets):
            item.reserved_product_id = products[0].id
    elif all_verified:
        status = "infeasible"
        note = "Verified options currently exceed the total budget."
    elif any(item.discovery == "searching" for item in open_items):
        status = "surveying"
        note = "Surveying verified store prices before finalising the budget split."
    else:
        status = "estimating"
        note = "Using category price ranges until every item has verified store prices."

    look.total_spent_minor = spent
    look.remaining_budget_minor = remaining
    look.budget_plan = BudgetPlan(
        revision=look.plan_revision,
        status=status,
        feasible=feasible,
        minimum_complete_total_minor=minimum_total,
        planned_total_minor=spent + sum(planned),
        verified_item_count=verified_count,
        open_item_count=len(open_items),
        note=note,
    )
    return look
