import httpx
from fastapi import HTTPException

from app.config import Settings


async def lookup_barcode(barcode: str, settings: Settings) -> dict:
    if not settings.enable_open_food_facts:
        raise HTTPException(
            501, "Barcode lookup is not connected yet. Use typed label text for the demo."
        )
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(
                f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json",
                params={"fields": "product_name,ingredients_text,allergens_tags,traces_tags"},
                headers={"User-Agent": settings.open_food_facts_user_agent},
            )
            if response.status_code == 404:
                raise HTTPException(404, "Barcode not found. Enter the label text or use a photo.")
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Food lookup is unavailable. Try typed label text.") from None
    if data.get("status") != 1 or not data.get("product", {}).get("ingredients_text"):
        raise HTTPException(404, "No ingredient label found. Enter the label text or use a photo.")
    return data["product"]
