"""Look state transitions shared by the board API and the stylist's tools.

All invariants live here: budget arithmetic, which products may be locked,
checklist confirmation and shortlist selection. Agent tools and HTTP routes are
thin adapters, so the model cannot do anything the board UI could not.
"""

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Callable

from pydantic import ValidationError

from app.clothes.sellers import is_small_business, retailer_priority
from app.memory.store import Store
from app.schemas import (
    MAX_CHECKLIST_ITEMS,
    CatalogProduct,
    ChecklistChoice,
    ChecklistItem,
    Look,
    LookBrief,
    PieceSpec,
    ProductFeedback,
    now,
)
from app.tools.budget import allocate_budget
from app.tools.product_search import seed_catalog

SHORTLIST_SIZE = 6
POOL_SIZE = 24
SMALL_BUSINESS_BOOST = 10
# Below this fit score a product is a mismatch (wrong item, bulk pack…); show nothing instead.
MIN_FIT = 35
# A product above the item's planned budget is still offered when it fits this well.
STRETCH_FIT = 60
MAX_STRETCH = 2
# Shortlist slots kept for independent stores when one qualifies, by retailer policy.
INDEPENDENT_SLOTS = {"popular_first": 1, "balanced": 2}
INDEPENDENT_LABELS = {"independent", "verified_small_business"}


class LookError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def product_id(url: str) -> str:
    return "p_" + hashlib.sha256(url.encode()).hexdigest()[:12]


def shortlist(
    item: ChecklistItem,
    policy: str = "popular_first",
    preferred_platforms: list[str] | None = None,
    remaining_budget_minor: int | None = None,
) -> list[CatalogProduct]:
    """Deterministic shortlist: budget, stock and rejections first, then style score.

    Liked products stay at the front. Under popular-first and balanced policies a
    qualifying independent store keeps at least one slot, so smaller sellers are
    seen without hiding the big marketplaces. When too few products fit the
    item's planned budget, up to two strong matches that still fit the remaining
    total budget are offered as clearly labelled stretch picks.
    """
    usable = [
        p
        for p in item.pool
        if p.id not in item.rejected_ids
        and p.availability != "out_of_stock"
        and (p.style_score is None or p.style_score >= MIN_FIT or p.source == "user")
    ]
    eligible = [p for p in usable if p.price_minor <= item.budget_cap_minor]
    user_added = [p for p in eligible if p.source == "user"]
    eligible = [p for p in eligible if p.source != "user"]
    liked = {f.product_id for f in item.feedback if f.sentiment == "like"}
    # Accept the old values for callers/persisted clients while new APIs use the
    # clearer retailer policy names.
    policy = {
        "off": "popular_first",
        "prefer": "independent_first",
        "only": "independent_only",
    }.get(policy, policy)
    if policy == "independent_only":
        eligible = [p for p in eligible if p.seller_label in INDEPENDENT_LABELS]

    def rank(product: CatalogProduct):
        fit = -(product.style_score or 50)
        store = retailer_priority(product.url, product.seller_label, preferred_platforms)
        loved = 0 if product.id in liked else 1
        if policy == "popular_first":
            return (loved, store, fit, product.price_minor)
        if policy in {"independent_first", "independent_only"}:
            verified = 0 if is_small_business(product.seller_label) else 1
            independent = 0 if product.seller_label in INDEPENDENT_LABELS else 1
            return (loved, independent, verified, fit, store, product.price_minor)
        return (loved, fit, store, product.price_minor)

    ranked = sorted(eligible, key=rank)
    slots = max(0, SHORTLIST_SIZE - len(user_added))
    top = ranked[:slots]
    wanted = INDEPENDENT_SLOTS.get(policy, 0)
    spare = [p for p in ranked[slots:] if p.seller_label in INDEPENDENT_LABELS]
    while spare and top and sum(p.seller_label in INDEPENDENT_LABELS for p in top) < wanted:
        # Replace the lowest-ranked popular pick the user has not liked.
        swap = next(
            (i for i in range(len(top) - 1, -1, -1)
             if top[i].seller_label not in INDEPENDENT_LABELS and top[i].id not in liked),
            None,
        )
        if swap is None:
            break
        top[swap] = spare.pop(0)

    picks = user_added + top
    free = min(MAX_STRETCH, SHORTLIST_SIZE - len(picks))
    if free > 0 and remaining_budget_minor:
        shown = {p.id for p in picks}
        stretch = sorted(
            (
                p for p in usable
                if p.id not in shown
                and p.source != "user"
                and item.budget_cap_minor < p.price_minor <= remaining_budget_minor
                and (p.id in liked or (p.style_score or 0) >= STRETCH_FIT)
                and (policy != "independent_only" or p.seller_label in INDEPENDENT_LABELS)
            ),
            key=lambda p: (0 if p.id in liked else 1, -(p.style_score or 0), p.price_minor),
        )
        picks += [p.model_copy(update={"stretch": True}) for p in stretch[:free]]
    return picks


def refresh(look: Look) -> Look:
    """Recompute budget caps and candidates; never calls a model."""
    allocate_budget(look)
    catalog = seed_catalog() if look.mode == "board" else []
    for item in look.items:
        if item.status != "open":
            item.candidates = []
        elif look.mode == "board":
            item.candidates = [
                p
                for p in catalog
                if p.category == item.category and p.price_minor <= item.budget_cap_minor
            ]
        else:
            item.candidates = shortlist(
                item, look.brief.retailer_policy, look.brief.platforms,
                look.remaining_budget_minor,
            )
    return look


class LookService:
    def __init__(self, store: Store):
        self.store = store
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.listeners: list[Callable[[str, Look, str], None]] = []

    # ------------------------------------------------------------------ storage
    async def get(self, uid: str, look_id: str) -> Look:
        record = await self.store.get(uid, "looks", look_id)
        if record is None:
            raise LookError(404, "Record not found.")
        # Hydrate records written before budget plans and retailer policies
        # existed so older saved looks immediately receive the current plan.
        return refresh(Look.model_validate(record))

    async def list_looks(self, uid: str) -> list[Look]:
        return [
            refresh(Look.model_validate(record)) for record in await self.store.list(uid, "looks")
        ]

    async def find_for_session(self, uid: str, session_id: str) -> Look | None:
        """Return the newest agent look created for a conversation, if one exists."""
        matches = [
            look
            for look in await self.list_looks(uid)
            if look.mode == "agent" and look.session_id == session_id
        ]
        return max(matches, key=lambda look: look.updated_at) if matches else None

    async def delete_for_sessions(self, uid: str, session_ids: set[str]) -> int:
        """Permanently delete agent looks that belong to the given conversations."""
        doomed = [
            look
            for look in await self.list_looks(uid)
            if look.mode == "agent" and look.session_id in session_ids
        ]
        for look in doomed:
            async with self._locks[look.id]:
                await self.store.delete(uid, "looks", look.id)
            self._locks.pop(look.id, None)
        return len(doomed)

    async def save(self, uid: str, look: Look) -> Look:
        look.revision += 1
        look.updated_at = now()
        await self.store.put(uid, "looks", look.id, look.model_dump(mode="json"))
        return look

    async def mutate(
        self,
        uid: str,
        look_id: str,
        change: Callable[[Look], None],
        event="",
        *,
        plan_change: bool = False,
    ) -> Look:
        """Serialised read-modify-write; `change` raises LookError to reject."""
        async with self._locks[look_id]:
            look = await self.get(uid, look_id)
            change(look)
            if plan_change:
                # Running searches keep going: verified products are facts that do not
                # depend on the plan, and each item's newest search job owns its results.
                look.plan_revision += 1
            try:
                refresh(look)
            except ValueError as error:
                raise LookError(422, str(error)) from None
            saved = await self.save(uid, look)
        for listener in self.listeners:
            listener(uid, saved, event)
        return saved

    # ------------------------------------------------------------------ creation
    async def create(self, uid: str, look: Look) -> Look:
        refresh(look)
        return await self.save(uid, look)

    async def create_for_session(self, uid: str, session_id: str, brief: LookBrief) -> Look:
        # A provider failure may happen after this write but before ADK persists the
        # tool-response state. Replaying save_brief must reconnect to the same board,
        # not create another orphaned look.
        if existing := await self.find_for_session(uid, session_id):
            return await self.update_brief(uid, existing.id, brief.model_dump())
        look_id = hashlib.sha256(f"agent-look:{session_id}".encode()).hexdigest()[:32]
        look = Look(
            id=look_id, brief=brief, items=[], mode="agent", session_id=session_id,
            status="exploring" if brief.total_budget_minor is None else "awaiting_checklist",
        )
        look.remaining_budget_minor = brief.total_budget_minor or 0
        return await self.create(uid, look)

    async def update_brief(self, uid: str, look_id: str, changes: dict) -> Look:
        def change(look: Look):
            data = look.brief.model_dump()
            data.update({k: v for k, v in changes.items() if v is not None})
            if changes.get("retailer_policy") is None and changes.get("small_business") is not None:
                data["retailer_policy"] = {
                    "off": "popular_first",
                    "prefer": "independent_first",
                    "only": "independent_only",
                }[changes["small_business"]]
            try:
                brief = LookBrief.model_validate(data)
            except ValidationError as error:
                fields = ", ".join(str(e["loc"][0]) for e in error.errors()[:3])
                raise LookError(422, f"Invalid brief values: {fields}.") from None
            if (brief.total_budget_minor or 0) < look.total_spent_minor:
                raise LookError(422, "The new budget is below what is already selected.")
            look.brief = brief

        return await self.mutate(uid, look_id, change, "brief", plan_change=True)

    async def replan(self, uid: str, look_id: str) -> Look:
        """Create a new plan revision while reusing every verified product pool."""
        return await self.mutate(uid, look_id, lambda look: None, "replanned", plan_change=True)

    async def refine(
        self,
        uid: str,
        look_id: str,
        *,
        kind: str,
        request: str = "",
        colour: str = "",
        preserve_selected: bool = True,
    ) -> Look:
        directions = {
            "cheaper": "Find a cheaper version of this look.",
            "more_formal": "Make the look more formal.",
            "more_casual": "Make the look more casual.",
            "change_colour": f"Use {colour}." if colour else "Change the colour palette.",
            "popular_stores_only": "Prefer well-known retailers.",
            "custom": request,
        }
        if kind not in directions:
            raise LookError(422, "Choose a supported look refinement.")

        def change(look: Look):
            direction = request or directions[kind]
            if direction:
                look.brief.description = " ".join(
                    part for part in (look.brief.description, direction) if part
                )[-2000:]
            if kind == "change_colour" and colour:
                look.brief.colours = [colour]
            if kind == "popular_stores_only":
                look.brief.retailer_policy = "popular_first"
                look.brief.small_business = "off"
            for item in look.items:
                if item.status == "open":
                    item.hints = [*item.hints, direction][-8:]
                elif item.status == "locked" and not preserve_selected:
                    item.status = "open"
                    item.chosen_product = None
                    item.hints = [*item.hints, direction][-8:]
            if look.status == "assembled":
                look.status = "shopping"

        return await self.mutate(uid, look_id, change, "refined", plan_change=True)

    # ------------------------------------------------------------------ checklist
    async def propose_checklist(self, uid: str, look_id: str, pieces: list[PieceSpec]) -> Look:
        def change(look: Look):
            if look.brief.total_budget_minor is None:
                raise LookError(409, "Ask for the total budget before proposing a checklist.")
            if any(item.status == "locked" for item in look.items):
                raise LookError(
                    409, "Items are already selected; add or remove single items instead."
                )
            unique = list({piece.category: piece for piece in pieces}.values())
            if not unique:
                raise LookError(422, "Propose at least one item.")
            look.items = [
                ChecklistItem(category=p.category, target=p.target)
                for p in unique[:MAX_CHECKLIST_ITEMS]
            ]
            look.status = "awaiting_checklist"

        return await self.mutate(uid, look_id, change, "checklist_proposed", plan_change=True)

    async def confirm_checklist(
        self, uid: str, look_id: str, choices: list[ChecklistChoice]
    ) -> Look:
        def change(look: Look):
            if look.status != "awaiting_checklist":
                raise LookError(409, "Checklist already confirmed. Use item actions to change it.")
            previous = {item.category: item for item in look.items}
            look.items = [
                ChecklistItem(
                    category=choice.category,
                    status=choice.status,
                    target=choice.target or getattr(previous.get(choice.category), "target", ""),
                    hints=getattr(previous.get(choice.category), "hints", []),
                )
                for choice in choices
            ]
            look.status = "shopping"

        return await self.mutate(uid, look_id, change, "checklist_confirmed", plan_change=True)

    async def add_item(self, uid: str, look_id: str, category: str, target: str = "") -> Look:
        def change(look: Look):
            existing = next((i for i in look.items if i.category == category), None)
            if existing and existing.status != "removed":
                raise LookError(409, f"'{category}' is already on the checklist.")
            if existing:
                existing.status, existing.target = "open", target or existing.target
                return
            if len([i for i in look.items if i.status != "removed"]) >= MAX_CHECKLIST_ITEMS:
                raise LookError(422, f"A look can have at most {MAX_CHECKLIST_ITEMS} items.")
            look.items.append(ChecklistItem(category=category, target=target))
            if look.status == "assembled":
                look.status = "shopping"

        return await self.mutate(uid, look_id, change, "item_added", plan_change=True)

    # ------------------------------------------------------------------ item actions
    async def item_action(
        self, uid: str, look_id: str, item_id: str, action: str, product_id: str | None = None
    ) -> Look:
        def change(look: Look):
            if look.status == "awaiting_checklist":
                raise LookError(409, "Confirm your checklist first.")
            item = find_item(look, item_id)
            if action == "lock":
                if item.status != "open":
                    raise LookError(409, "Reopen or swap this item before choosing a product.")
                product = next((p for p in item.candidates if p.id == product_id), None)
                if product is None or product.price_minor > look.remaining_budget_minor:
                    raise LookError(422, "Choose a current candidate within the remaining budget.")
                item.chosen_product = product.model_copy(update={"stretch": False})
                item.status = "locked"
            elif action == "reject":
                if not product_id or not any(
                    p.id == product_id for p in item.pool + item.candidates
                ):
                    raise LookError(422, "That product is not a candidate for this item.")
                item.rejected_ids = [*item.rejected_ids, product_id][-50:]
            else:
                item.status = {
                    "swap": "open",
                    "own": "owned",
                    "remove": "removed",
                    "reopen": "open",
                }[action]
                if action == "swap" and item.chosen_product:
                    item.rejected_ids = [*item.rejected_ids, item.chosen_product.id][-50:]
                item.chosen_product = None
            if look.status == "assembled" or action != "reject":
                look.status = "shopping"

        return await self.mutate(uid, look_id, change, f"item_{action}", plan_change=True)

    async def apply_discovery(
        self,
        uid: str,
        look_id: str,
        item_id: str,
        *,
        status: str,
        pool: list[CatalogProduct] | None = None,
        note: str = "",
        replace: bool = False,
        expected_plan_revision: int | None = None,
    ) -> Look:
        def change(look: Look):
            if expected_plan_revision is not None and look.plan_revision != expected_plan_revision:
                return
            item = next((i for i in look.items if i.id == item_id), None)
            if item is None:
                return  # removed while discovery was running
            item.discovery, item.discovery_note = status, note[:300]
            if pool is None:
                return
            # User-added and liked products survive every new search.
            liked = {f.product_id for f in item.feedback if f.sentiment == "like"}
            kept = [p for p in item.pool if p.source == "user" or p.id in liked]
            seen = {p.id for p in kept}
            merged = kept + [p for p in pool if p.id not in seen and not seen.add(p.id)]
            if not replace:
                merged += [p for p in item.pool if p.id not in seen and not seen.add(p.id)]
            item.pool = merged[:POOL_SIZE]

        return await self.mutate(uid, look_id, change, f"discovery_{status}")

    async def set_scores(
        self,
        uid: str,
        look_id: str,
        item_id: str,
        scores: dict[str, tuple[int, str]],
        expected_plan_revision: int | None = None,
    ):
        def change(look: Look):
            if expected_plan_revision is not None and look.plan_revision != expected_plan_revision:
                return
            item = next((i for i in look.items if i.id == item_id), None)
            if item is None:
                return
            for product in item.pool:
                if product.id in scores:
                    product.style_score, product.match_reason = scores[product.id]

        return await self.mutate(uid, look_id, change, "rescored")

    async def give_feedback(
        self,
        uid: str,
        look_id: str,
        item_id: str,
        product_id: str,
        sentiment: str,
        reasons: list[str] | None = None,
        note: str = "",
    ) -> Look:
        """Record a like/dislike on one candidate; a dislike also hides it."""

        def change(look: Look):
            item = find_item(look, item_id)
            product = next(
                (p for p in item.candidates + item.pool if p.id == product_id), None
            )
            if product is None:
                raise LookError(422, "That product is not a candidate for this item.")
            entry = ProductFeedback(
                product_id=product.id,
                title=product.title[:200],
                colour=product.colour[:40],
                price_minor=product.price_minor,
                retailer=product.retailer[:120],
                sentiment=sentiment,
                reasons=reasons or [],
                note=note,
            )
            earlier = [f for f in item.feedback if f.product_id != product.id]
            item.feedback = [*earlier, entry][-24:]
            if sentiment == "dislike":
                item.rejected_ids = [*item.rejected_ids, product.id][-50:]
            else:
                item.rejected_ids = [i for i in item.rejected_ids if i != product.id]

        return await self.mutate(uid, look_id, change, "feedback")

    async def add_user_product(
        self, uid: str, look_id: str, item_id: str, product: CatalogProduct
    ) -> Look:
        def change(look: Look):
            item = find_item(look, item_id)
            if item.status != "open":
                raise LookError(409, "Reopen this item before adding a product.")
            item.pool = [product] + [p for p in item.pool if p.id != product.id][: POOL_SIZE - 1]
            item.rejected_ids = [i for i in item.rejected_ids if i != product.id]

        return await self.mutate(uid, look_id, change, "user_product", plan_change=True)

    async def assemble(self, uid: str, look_id: str, styling_note: str | None = None) -> Look:
        def change(look: Look):
            if look.status == "awaiting_checklist" or any(i.status == "open" for i in look.items):
                raise LookError(409, "Resolve each checklist item before assembling your look.")
            if all(i.status == "removed" for i in look.items):
                raise LookError(409, "Keep at least one item in your look.")
            if styling_note:
                look.styling_note = styling_note
            look.status = "assembled"

        return await self.mutate(uid, look_id, change, "assembled")


def find_item(look: Look, item_id_or_category: str) -> ChecklistItem:
    key = item_id_or_category.strip().lower()
    item = next((i for i in look.items if i.id == item_id_or_category or i.category == key), None)
    if item is None:
        raise LookError(404, "Checklist item not found.")
    return item
