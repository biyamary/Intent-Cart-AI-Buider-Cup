"""Stylist coordinator tools.

Identity and the active look come from the ADK ToolContext (authenticated user,
session state), never from model arguments. Every change goes through
LookService, so the model can only do what the board UI can. Tools return small
JSON results; failures come back as {"error": ...} so the conversation continues.
"""

import json
import logging
from dataclasses import dataclass
from functools import wraps
from uuid import uuid4

from google.adk.tools import FunctionTool, ToolContext
from google.genai import types
from pydantic import ValidationError

from app.clothes.discovery import Discovery, rupees, to_product
from app.clothes.pages import fetch_image, fetch_public, normalise_url, read_product
from app.clothes.sellers import classify
from app.clothes.service import LookError, LookService, find_item, product_id
from app.clothes.studio import Studio, StudioError, concept_prompt
from app.config import Settings
from app.schemas import (
    MAX_CHECKLIST_ITEMS,
    CatalogProduct,
    ChecklistChoice,
    ChecklistItem,
    ConceptImage,
    Look,
    LookBrief,
    PieceSpec,
)

logger = logging.getLogger(__name__)
LOOK_KEY = "look:id"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass
class ShopServices:
    settings: Settings
    looks: LookService
    discovery: Discovery
    studio: Studio


def inr(minor: int) -> str:
    return f"₹{rupees(minor):,}"


def product_line(p: CatalogProduct) -> dict:
    line = {
        "id": p.id,
        "title": p.title,
        "price": inr(p.price_minor),
        "store": p.retailer,
        "seller": p.seller_label,
    }
    if p.style_score is not None:
        line["fit"] = p.style_score
    if p.match_reason:
        line["why"] = p.match_reason
    if p.source == "user":
        line["added_by_user"] = True
    return line


def snapshot(look: Look, *, candidates: bool = True) -> dict:
    items = []
    for item in look.items:
        entry = {"category": item.category, "status": item.status, "target": item.target}
        if item.status == "open":
            entry["budget_cap"] = inr(item.budget_cap_minor)
            entry["budget_role"] = item.budget_role
            entry["planned_budget"] = inr(item.planned_budget_minor)
            entry["price_range"] = {
                "low": inr(item.price_band.low_minor),
                "typical": inr(item.price_band.typical_minor),
                "high": inr(item.price_band.high_minor),
                "sample_count": item.price_band.sample_count,
                "source": item.price_band.source,
            }
            entry["survey"] = item.survey_status
            if item.reserved_product_id:
                entry["completion_option_reserved"] = True
            entry["search"] = item.discovery
            if item.discovery_note:
                entry["search_note"] = item.discovery_note
            if candidates:
                entry["candidates"] = [product_line(p) for p in item.candidates]
        if item.chosen_product:
            entry["selected"] = product_line(item.chosen_product)
        if item.boutiques:
            entry["local_boutiques"] = [b.name for b in item.boutiques]
        items.append(entry)
    brief = look.brief
    return {
        "look_status": look.status,
        "occasion": brief.occasion,
        "budget": inr(brief.total_budget_minor),
        "spent": inr(look.total_spent_minor),
        "remaining": inr(look.remaining_budget_minor),
        "budget_plan": {
            "status": look.budget_plan.status,
            "feasible": look.budget_plan.feasible,
            "minimum_complete_total": inr(look.budget_plan.minimum_complete_total_minor),
            "verified_items": look.budget_plan.verified_item_count,
            "open_items": look.budget_plan.open_item_count,
            "note": look.budget_plan.note,
            "revision": look.budget_plan.revision,
        },
        "preferences": {
            k: v
            for k, v in {
                "event_date": brief.event_date,
                "sizes": brief.sizes,
                "colours": brief.colours,
                "avoid_colours": brief.avoid_colours,
                "platforms": brief.platforms,
                "delivery": brief.delivery_city or brief.delivery_pin,
                "retailer_policy": brief.retailer_policy,
                "small_business": brief.small_business,
            }.items()
            if v
        },
        "items": items,
        "inspiration_count": len(look.inspiration),
        "concept_images": len(look.concepts),
    }


def describe_look(look: Look | None) -> str:
    """Compact context for the coordinator's instruction (data, not instructions)."""
    if look is None:
        return "Current look: none yet. Call save_brief once the occasion and budget are known."
    text = "Current look board (live data; trust it over earlier messages):\n" + json.dumps(
        snapshot(look), ensure_ascii=False
    )
    if look.references:
        text += (
            f"\nThe user's reference photo is on file ({len(look.references)} image(s)). "
            "To show a change to THEIR photo (e.g. different jewellery), call visualize_look "
            "with kind 'edit_reference'."
        )
    return text


def tool_errors(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (LookError, StudioError) as error:
            return {"error": getattr(error, "detail", None) or str(error)}
        except ValidationError as error:
            fields = ", ".join(".".join(map(str, e["loc"])) for e in error.errors()[:3])
            return {"error": f"Invalid values for: {fields}."}
        except Exception as error:  # noqa: BLE001 -- keep the conversation alive; no payload logs
            logger.warning(
                "Stylist tool failed: tool=%s error_type=%s", fn.__name__, type(error).__name__
            )
            return {"error": "That step is unavailable right now. Try again in a moment."}

    return wrapper


def build_stylist_tools(services: ShopServices) -> list[FunctionTool]:
    looks, discovery, studio, settings = (
        services.looks,
        services.discovery,
        services.studio,
        services.settings,
    )

    async def current(tool_context: ToolContext) -> Look:
        look_id = tool_context.state.get(LOOK_KEY)
        if not look_id:
            recovered = await looks.find_for_session(tool_context.user_id, tool_context.session.id)
            if recovered is None:
                raise LookError(
                    409, "No look yet: call save_brief with the occasion and budget first."
                )
            tool_context.state[LOOK_KEY] = recovered.id
            return recovered
        return await looks.get(tool_context.user_id, look_id)

    async def restart_uncovered(uid: str, look: Look) -> Look:
        ids = [
            item.id
            for item in look.items
            if item.status == "open" and not item.pool and item.discovery != "searching"
        ]
        if ids:
            await discovery.start(uid, look.id, ids)
            return await looks.get(uid, look.id)
        return look

    # ------------------------------------------------------------------ step 1–2
    @tool_errors
    async def save_brief(
        tool_context: ToolContext,
        occasion: str | None = None,
        total_budget_inr: int | None = None,
        description: str | None = None,
        event_date: str | None = None,
        sizes: str | None = None,
        colours: list[str] | None = None,
        avoid_colours: list[str] | None = None,
        platforms: list[str] | None = None,
        delivery_city: str | None = None,
        delivery_pin: str | None = None,
        retailer_policy: str | None = None,
        small_business: str | None = None,
    ) -> dict:
        """Create or update the look brief on the user's look board.

        Call as soon as the occasion and total budget are known, and again whenever
        the user changes a preference. Only pass fields the user stated or confirmed.

        Args:
            occasion: The event, e.g. "Sister's mehendi".
            total_budget_inr: Total budget for the whole look in whole rupees.
            description: The style the user described, including modifiers such as
                "more affordable accessories".
            event_date: Event date as the user said it, e.g. "2026-11-14".
            sizes: Sizes as the user stated them, e.g. "M top, UK 5 shoes".
            colours: Preferred colours.
            avoid_colours: Colours to avoid.
            platforms: Preferred shops or platforms.
            delivery_city: City for delivery or local shopping.
            delivery_pin: 6-digit Indian PIN code.
            retailer_policy: "popular_first" (default), "balanced",
                "independent_first" or "independent_only".
            small_business: Deprecated compatibility value: "prefer", "only" or "off".
        """
        changes = {
            "occasion": occasion,
            "description": description,
            "event_date": event_date,
            "sizes": sizes,
            "colours": colours,
            "avoid_colours": avoid_colours,
            "platforms": platforms,
            "delivery_city": delivery_city,
            "delivery_pin": delivery_pin,
            "retailer_policy": retailer_policy,
            "small_business": small_business,
            "total_budget_minor": total_budget_inr * 100 if total_budget_inr else None,
        }
        look_id = tool_context.state.get(LOOK_KEY)
        uid = tool_context.user_id
        if look_id:
            look = await looks.update_brief(uid, look_id, changes)
            if look.status == "shopping":
                search_changed = any(
                    changes.get(key) is not None
                    for key in (
                        "description",
                        "sizes",
                        "colours",
                        "avoid_colours",
                        "platforms",
                        "retailer_policy",
                        "small_business",
                    )
                )
                ids = [
                    item.id
                    for item in look.items
                    if item.status == "open"
                    and (search_changed or (not item.pool and item.discovery != "searching"))
                ]
                if ids:
                    await discovery.start(uid, look.id, ids, request="Preferences updated")
                    look = await looks.get(uid, look.id)
        else:
            if not occasion or not total_budget_inr:
                return {"error": "Both occasion and total_budget_inr are needed to start a look."}
            brief = LookBrief.model_validate({k: v for k, v in changes.items() if v is not None})
            look = await looks.create_for_session(uid, tool_context.session.id, brief)
            tool_context.state[LOOK_KEY] = look.id
        return {"saved": True, "look": snapshot(look, candidates=False)}

    @tool_errors
    async def analyze_reference(tool_context: ToolContext, request: str = "") -> dict:
        """Analyse the user's reference image(s) and/or description into shoppable pieces.

        Use when the user attaches a photo or describes a look to recreate. Returns
        a summary, palette, style tags and proposed pieces with target descriptions.
        Follow with propose_checklist (adjusted for the user's wishes).

        Args:
            request: The user's request in their words, e.g. "recreate this Mehendi
                look with more affordable accessories".
        """
        look = await current(tool_context)
        names = list(
            dict.fromkeys(tool_context.state.get("temp:attachments", []) + look.references)
        )
        images = []
        for name in names[:3]:
            part = await tool_context.load_artifact(name)
            if part and part.inline_data and part.inline_data.mime_type in IMAGE_TYPES:
                images.append((part.inline_data.data, part.inline_data.mime_type))
        if not images and not (request or look.brief.description):
            return {"error": "No reference image or description to analyse."}
        analysis = await studio.analyze_reference(request or look.brief.description, images, look)

        def change(saved: Look):
            saved.analysis = analysis
            saved.references = names[:6]

        await looks.mutate(tool_context.user_id, look.id, change, "analysis")
        return {"images_analysed": len(images), "analysis": analysis.model_dump()}

    # ------------------------------------------------------------------ step 3
    @tool_errors
    async def propose_checklist(tool_context: ToolContext, items: list[dict]) -> dict:
        """Put a draft shopping checklist on the board for the user to review.

        The user confirms it on the board or by agreeing in chat (then call
        start_shopping). Do not call this once products are selected; use
        update_checklist instead.

        Args:
            items: Up to 10 objects {"category": ..., "target": ...}. Use categories
                outfit, earrings, necklace, bangles, footwear, handbag, hair accessories,
                or a short custom one (e.g. "dupatta"). `target` is a concrete
                searchable description (colour, material, style).
        """
        look = await current(tool_context)
        pieces = [PieceSpec.model_validate(i) for i in items[:MAX_CHECKLIST_ITEMS]]
        look = await looks.propose_checklist(tool_context.user_id, look.id, pieces)
        return {"proposed": True, "look": snapshot(look, candidates=False)}

    @tool_errors
    async def update_checklist(
        tool_context: ToolContext, category: str, action: str, target: str = ""
    ) -> dict:
        """Add, remove, mark as owned, or restore one checklist item.

        Args:
            category: The item category, e.g. "bangles" or a custom item like "dupatta".
            action: "add", "remove", "own" (user already has it) or "restore".
            target: For "add": a concrete description of the piece.
        """
        look = await current(tool_context)
        uid, key = tool_context.user_id, category.strip().lower()
        if look.status == "awaiting_checklist":

            def change(saved: Look):
                existing = next((i for i in saved.items if i.category == key), None)
                if action == "add":
                    if existing:
                        existing.status, existing.target = "open", target or existing.target
                    elif len(saved.items) >= MAX_CHECKLIST_ITEMS:
                        raise LookError(422, "The checklist is full.")
                    else:
                        saved.items.append(ChecklistItem(category=key, target=target))
                    return
                if existing is None:
                    raise LookError(404, f"'{key}' is not on the checklist.")
                existing.status = {"remove": "removed", "own": "owned", "restore": "open"}[action]

            look = await looks.mutate(uid, look.id, change, "checklist_edit", plan_change=True)
        elif action == "add":
            look = await looks.add_item(uid, look.id, key, target)
            await discovery.start(uid, look.id, [find_item(look, key).id])
            look = await looks.get(uid, look.id)
        else:
            mapped = {"remove": "remove", "own": "own", "restore": "reopen"}[action]
            look = await looks.item_action(uid, look.id, find_item(look, key).id, mapped)
            if mapped == "reopen":
                await discovery.start(uid, look.id, [find_item(look, key).id])
                look = await looks.get(uid, look.id)
        if look.status == "shopping":
            look = await restart_uncovered(uid, look)
        return {"updated": True, "look": snapshot(look, candidates=False)}

    @tool_errors
    async def start_shopping(tool_context: ToolContext) -> dict:
        """Confirm the draft checklist and start searching stores for every open item.

        Only call after the user has clearly approved the checklist in their latest
        message. Search runs in the background; results appear on the board.
        """
        look = await current(tool_context)
        if look.status != "awaiting_checklist":
            return {
                "error": "The checklist is already confirmed. Use find_products to search again."
            }
        choices = [
            ChecklistChoice(
                category=i.category,
                status=i.status if i.status != "locked" else "open",
                target=i.target,
            )
            for i in look.items
        ]
        look = await looks.confirm_checklist(tool_context.user_id, look.id, choices)
        started = await discovery.start(tool_context.user_id, look.id)
        return {
            "confirmed": True,
            "searching": [i.category for i in look.items if i.id in started],
            "note": "Searching stores in the background; results will appear on the board.",
        }

    # ------------------------------------------------------------------ step 4–5
    @tool_errors
    async def find_products(
        tool_context: ToolContext, categories: list[str] | None = None, request: str = ""
    ) -> dict:
        """Search stores again for open items (all open items if categories is empty).

        Args:
            categories: Item categories to search, e.g. ["earrings"].
            request: Extra guidance from the user, e.g. "more silver, less heavy".
        """
        look = await current(tool_context)
        ids = [find_item(look, c).id for c in categories] if categories else None
        if ids and not request:
            # Don't restart searches that are still running.
            ids = [i for i in ids if find_item(look, i).discovery != "searching"] or None
            if ids is None:
                return {"note": "Those items are still being searched; results will appear soon."}
        started = await discovery.start(tool_context.user_id, look.id, ids, request=request)
        if not started:
            return {"error": "No open items to search (or search is disabled)."}
        return {"searching": len(started), "note": "Results will appear on the board shortly."}

    @tool_errors
    async def find_alternatives(
        tool_context: ToolContext, category: str, request: str, max_price_inr: int | None = None
    ) -> dict:
        """Find different options for one item, e.g. cheaper or matching a locked piece.

        Args:
            category: The item, e.g. "earrings".
            request: What should change, e.g. "cheaper, silver, to match the lehenga".
            max_price_inr: Optional price ceiling in rupees (cannot exceed the item's budget).
        """
        look = await current(tool_context)
        item = find_item(look, category)
        if item.status != "open":
            return {
                "error": f"'{item.category}' is {item.status}; swap it first to see alternatives."
            }

        def remember(saved: Look):
            target = find_item(saved, item.id)
            target.hints = [*target.hints, request][-4:]

        look = await looks.mutate(tool_context.user_id, look.id, remember, "hint", plan_change=True)
        started = await discovery.start(
            tool_context.user_id,
            look.id,
            [item.id],
            request=request,
            max_price_minor=max_price_inr * 100 if max_price_inr else None,
        )
        await restart_uncovered(
            tool_context.user_id, await looks.get(tool_context.user_id, look.id)
        )
        return {"searching": bool(started), "note": "New options will appear on the board shortly."}

    @tool_errors
    async def select_product(tool_context: ToolContext, category: str, product_id: str) -> dict:
        """Lock a product into the look. Only ids from the current candidates are accepted.

        After locking, remaining items are re-ranked to match it.

        Args:
            category: The item, e.g. "outfit".
            product_id: The candidate id shown in the look board data (e.g. "p_1a2b3c4d5e6f").
        """
        look = await current(tool_context)
        item = find_item(look, category)
        look = await looks.item_action(tool_context.user_id, look.id, item.id, "lock", product_id)
        await discovery.rescore(tool_context.user_id, look.id)
        look = await restart_uncovered(tool_context.user_id, look)
        return {"selected": True, "look": snapshot(look, candidates=False)}

    @tool_errors
    async def change_item(
        tool_context: ToolContext, category: str, action: str, product_id: str | None = None
    ) -> dict:
        """Change one item without rebuilding the look.

        Args:
            category: The item, e.g. "footwear".
            action: "swap" (unlock and find other options), "own", "remove", "reopen",
                or "reject" (hide one candidate; needs product_id).
            product_id: For "reject": the candidate to hide.
        """
        look = await current(tool_context)
        item = find_item(look, category)
        look = await looks.item_action(tool_context.user_id, look.id, item.id, action, product_id)
        refreshed = find_item(look, item.id)
        if action in {"swap", "reopen", "reject"} and len(refreshed.candidates) < 2:
            await discovery.start(tool_context.user_id, look.id, [item.id])
            look = await looks.get(tool_context.user_id, look.id)
        look = await restart_uncovered(tool_context.user_id, look)
        return {"changed": True, "look": snapshot(look)}

    @tool_errors
    async def refine_look(
        tool_context: ToolContext,
        kind: str,
        request: str = "",
        colour: str = "",
        preserve_selected: bool = True,
    ) -> dict:
        """Update the whole look after results are shown and search again.

        Args:
            kind: "cheaper", "more_formal", "more_casual", "change_colour",
                "popular_stores_only", or "custom".
            request: The user's instructions when kind is "custom", or extra detail.
            colour: New colour when kind is "change_colour".
            preserve_selected: Keep selected pieces by default. Set false only when
                the user asks to redo the entire look.
        """
        look = await current(tool_context)
        look = await looks.refine(
            tool_context.user_id,
            look.id,
            kind=kind,
            request=request,
            colour=colour,
            preserve_selected=preserve_selected,
        )
        ids = [item.id for item in look.items if item.status == "open"]
        started = (
            await discovery.start(
                tool_context.user_id,
                look.id,
                ids,
                request=request or kind.replace("_", " "),
            )
            if ids
            else []
        )
        return {
            "updated": True,
            "searching": len(started),
            "preserved_selected": preserve_selected,
            "look": snapshot(await looks.get(tool_context.user_id, look.id), candidates=False),
        }

    @tool_errors
    async def add_product_link(
        tool_context: ToolContext, category: str, url: str, price_inr: int | None = None
    ) -> dict:
        """Add a product the user found themselves (e.g. a link or an Instagram shop).

        The page is checked for a price. If none can be read, pass the price the
        user says they see; it will be shown as user-entered.

        Args:
            category: The item it is for.
            url: The product link the user pasted.
            price_inr: Price in rupees as stated by the user, if the page has none.
        """
        look = await current(tool_context)
        item = find_item(look, category)
        product = await verify_link(item.category, url, price_inr * 100 if price_inr else None)
        look = await looks.add_user_product(tool_context.user_id, look.id, item.id, product)
        await restart_uncovered(tool_context.user_id, look)
        return {"added": product_line(product), "price_from": product.price_source}

    @tool_errors
    async def get_look(tool_context: ToolContext) -> dict:
        """Read the current look board, including candidate ids, prices and search progress."""
        return snapshot(await current(tool_context))

    # ------------------------------------------------------------------ imagination
    @tool_errors
    async def find_inspiration(tool_context: ToolContext, request: str = "") -> dict:
        """Find Pinterest pins and editorial images for the look and show them on the board.

        Args:
            request: What to look for, e.g. "pastel mehendi looks with mirror work".
        """
        look = await current(tool_context)
        found = await studio.find_inspiration(look, request)
        if not found:
            return {"found": 0, "note": "No inspiration found for that search."}

        def change(saved: Look):
            existing = {i.url for i in saved.inspiration}
            saved.inspiration = (saved.inspiration + [i for i in found if i.url not in existing])[
                -12:
            ]

        await looks.mutate(tool_context.user_id, look.id, change, "inspiration")
        return {
            "found": len(found),
            "pinterest": sum(i.kind == "pinterest" for i in found),
            "titles": [i.title for i in found if i.title][:6],
        }

    @tool_errors
    async def visualize_look(
        tool_context: ToolContext, kind: str = "concept", instructions: str = ""
    ) -> dict:
        """Generate an AI concept image of the look and show it on the board.

        Args:
            kind: "edit_reference" whenever the user wants THEIR uploaded photo changed
                (e.g. "show my reference with silver jewellery"); "concept" for a new
                idea from the brief/checklist when no photo edit is asked for; "final"
                to compose the products they selected.
            instructions: The user's requested change or direction, in full, e.g.
                "oxidised silver jhumkas and choker instead of gold". It takes priority
                over the checklist.
        """
        look = await current(tool_context)
        images: list[tuple[bytes, str]] = []
        if kind == "edit_reference":
            for name in look.references[:1] or tool_context.state.get("temp:attachments", [])[:1]:
                part = await tool_context.load_artifact(name)
                if part and part.inline_data:
                    images.append((part.inline_data.data, part.inline_data.mime_type))
            if not images:
                return {"error": "There is no reference image to edit."}
        elif kind == "final":
            chosen = [
                i.chosen_product for i in look.items if i.status == "locked" and i.chosen_product
            ]
            for product in chosen[:6]:
                if product.image_url and (image := await fetch_image(product.image_url)):
                    images.append(image)
            if not images:
                return {"error": "Select some products with images first."}
        elif kind != "concept":
            return {"error": "kind must be concept, edit_reference or final."}
        data, mime = await studio.generate_concept(concept_prompt(kind, look, instructions), images)
        extension = {"image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        name = f"concept-{uuid4().hex[:10]}.{extension}"
        await tool_context.save_artifact(name, types.Part.from_bytes(data=data, mime_type=mime))
        caption = {
            "concept": "AI concept of the look",
            "edit_reference": "AI edit of your reference",
            "final": "AI composition of your selected pieces",
        }[kind]

        def change(saved: Look):
            saved.concepts = (
                saved.concepts + [ConceptImage(artifact=name, kind=kind, caption=caption)]
            )[-12:]

        await looks.mutate(tool_context.user_id, look.id, change, "concept")
        return {
            "image_created": True,
            "kind": kind,
            "note": "Shown on the board, labelled as an AI concept (not a product).",
        }

    @tool_errors
    async def find_local_boutiques(tool_context: ToolContext, category: str) -> dict:
        """Find independent local shops (Google Maps) for one item near the user's city.

        Useful for small businesses, in-person try-on, or when the event is too soon
        for delivery. Needs delivery_city or delivery_pin in the brief.

        Args:
            category: The item, e.g. "bangles".
        """
        look = await current(tool_context)
        item = find_item(look, category)
        boutiques = await studio.find_boutiques(look, item.category, item.target)

        def change(saved: Look):
            find_item(saved, item.id).boutiques = boutiques

        await looks.mutate(tool_context.user_id, look.id, change, "boutiques")
        return {"found": [b.name for b in boutiques]}

    # ------------------------------------------------------------------ step 6
    @tool_errors
    async def finish_look(tool_context: ToolContext) -> dict:
        """Assemble the final look (all items selected, owned or removed) with a styling note."""
        look = await current(tool_context)
        if look.status == "awaiting_checklist" or any(i.status == "open" for i in look.items):
            open_items = [i.category for i in look.items if i.status == "open"]
            return {"error": f"Still open: {', '.join(open_items) or 'checklist not confirmed'}."}
        try:
            note = await studio.styling_note(look)
        except Exception:  # noqa: BLE001 -- the note is optional
            note = ""
        look = await looks.assemble(tool_context.user_id, look.id, note or None)
        return {"assembled": True, "look": snapshot(look, candidates=False), "styling_note": note}

    functions = [
        save_brief,
        analyze_reference,
        propose_checklist,
        update_checklist,
        start_shopping,
        find_products,
        find_alternatives,
        select_product,
        change_item,
        refine_look,
        add_product_link,
        get_look,
        find_inspiration,
        visualize_look,
        finish_look,
    ]
    if settings.stylist_maps_enabled:
        functions.append(find_local_boutiques)
    return [FunctionTool(func=f) for f in functions]


async def verify_link(category: str, url: str, price_minor: int | None) -> CatalogProduct:
    """Verify a user-supplied product link; fall back to a user-entered price."""
    clean = normalise_url(url)
    if clean is None:
        raise LookError(422, "Use a full https:// product link.")
    facts, _ = await read_product(clean, fetch_public)
    if facts is not None:
        return to_product(facts, category).model_copy(update={"source": "user"})
    if price_minor is None:
        raise LookError(
            422, "No price could be read from that page. Ask the user for the price they see."
        )
    label, note = classify(clean)
    return CatalogProduct(
        id=product_id(clean),
        category=category,
        title="Added by you",
        price_minor=price_minor,
        retailer=clean.split("/")[2],
        url=clean,
        source="user",
        price_source="user",
        verification="user",
        match_reason="Added from your link; price as you entered it.",
        seller_label=label,
        seller_note=note,
    )
