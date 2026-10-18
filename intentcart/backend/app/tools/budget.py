from app.schemas import Look

WEIGHTS = {
    "outfit": 45,
    "footwear": 15,
    "earrings": 10,
    "necklace": 10,
    "handbag": 10,
    "bangles": 6,
    "hair accessories": 4,
}
# User-added categories (e.g. "dupatta", "clutch") share budget like a small accessory.
DEFAULT_WEIGHT = 6


def weight(category: str) -> int:
    return WEIGHTS.get(category, DEFAULT_WEIGHT)


def allocate_budget(look: Look) -> Look:
    """Largest-remainder allocation in paise; never allocate more than remains."""
    spent = sum(
        item.chosen_product.price_minor
        for item in look.items
        if item.status == "locked" and item.chosen_product
    )
    remaining = look.brief.total_budget_minor - spent
    if remaining < 0:
        raise ValueError("Selected products exceed the total budget.")
    open_items = [item for item in look.items if item.status == "open"]
    weight_sum = sum(weight(item.category) for item in open_items)
    for item in look.items:
        item.budget_cap_minor = (
            item.chosen_product.price_minor
            if item.status == "locked" and item.chosen_product
            else 0
        )
    if weight_sum:
        for item in open_items:
            item.budget_cap_minor = remaining * weight(item.category) // weight_sum
        spare = remaining - sum(item.budget_cap_minor for item in open_items)
        ranked = sorted(
            open_items,
            key=lambda item: remaining * weight(item.category) % weight_sum,
            reverse=True,
        )
        for item in ranked[:spare]:
            item.budget_cap_minor += 1
    look.total_spent_minor = spent
    look.remaining_budget_minor = remaining
    return look
