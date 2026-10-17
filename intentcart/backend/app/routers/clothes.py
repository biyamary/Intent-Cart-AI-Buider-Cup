from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.schemas import Explanation, ParsedBrief
from app.agents.stylist_agent import create_brief_agent, create_styling_agent
from app.auth import current_user
from app.dependencies import get_store, owned_record, profile_for
from app.memory.store import Store
from app.schemas import ChecklistItem, ConfirmChecklist, ItemAction, Look, LookBrief
from app.tools.budget import WEIGHTS
from app.tools.product_search import refresh_candidates

router = APIRouter(prefix="/clothes", tags=["clothes"])


async def save_look(store, uid, look):
    await store.put(uid, "looks", look.id, look.model_dump(mode="json"))
    return look


@router.post("/looks", response_model=Look, status_code=201)
async def create_look(
    brief: LookBrief,
    request: Request,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    profile = await profile_for(store, uid)
    categories = ["outfit", "earrings", "footwear", "handbag"]
    if request.app.state.settings.agent_mode == "gemini":
        parsed = await request.app.state.agents.run(
            create_brief_agent(request.app.state.settings),
            uid,
            {"brief": brief.model_dump(), "profile": profile.model_dump()},
            ParsedBrief,
        )
        categories = (
            list(dict.fromkeys(c for c in parsed.suggested_categories if c in WEIGHTS))
            or categories
        )
    look = Look(
        brief=brief,
        items=[ChecklistItem(category=category) for category in categories],
        remaining_budget_minor=brief.total_budget_minor,
    )
    return await save_look(store, uid, look)


@router.get("/looks", response_model=list[Look])
async def list_looks(uid: str = Depends(current_user), store: Store = Depends(get_store)):
    return await store.list(uid, "looks")


@router.get("/looks/{look_id}", response_model=Look)
async def get_look(
    look_id: str, uid: str = Depends(current_user), store: Store = Depends(get_store)
):
    return await owned_record(store, uid, "looks", look_id)


@router.post("/looks/{look_id}/checklist", response_model=Look)
async def confirm_checklist(
    look_id: str,
    body: ConfirmChecklist,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    look = Look.model_validate(await owned_record(store, uid, "looks", look_id))
    if look.status != "awaiting_checklist":
        raise HTTPException(409, "Checklist already confirmed. Use item actions to change it.")
    look.items = [ChecklistItem(category=item.category, status=item.status) for item in body.items]
    look.status = "shopping"
    return await save_look(store, uid, refresh_candidates(look))


@router.post("/looks/{look_id}/items/{item_id}", response_model=Look)
async def change_item(
    look_id: str,
    item_id: str,
    body: ItemAction,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    look = Look.model_validate(await owned_record(store, uid, "looks", look_id))
    if look.status == "awaiting_checklist":
        raise HTTPException(409, "Confirm your checklist first.")
    item = next((item for item in look.items if item.id == item_id), None)
    if item is None:
        raise HTTPException(404, "Checklist item not found.")
    if body.action == "lock":
        if item.status != "open":
            raise HTTPException(409, "Reopen or swap this item before choosing a product.")
        product = next((p for p in item.candidates if p.id == body.product_id), None)
        if product is None or product.price_minor > look.remaining_budget_minor:
            raise HTTPException(422, "Choose a current candidate within the remaining budget.")
        item.chosen_product, item.status = product, "locked"
    else:
        item.status = {"swap": "open", "own": "owned", "remove": "removed", "reopen": "open"}[
            body.action
        ]
        item.chosen_product = None
    look.status = "shopping"
    return await save_look(store, uid, refresh_candidates(look))


@router.post("/looks/{look_id}/assemble", response_model=Look)
async def assemble(
    look_id: str,
    request: Request,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    look = Look.model_validate(await owned_record(store, uid, "looks", look_id))
    if look.status == "awaiting_checklist" or any(item.status == "open" for item in look.items):
        raise HTTPException(409, "Resolve each checklist item before assembling your look.")
    if all(item.status == "removed" for item in look.items):
        raise HTTPException(409, "Keep at least one item in your look.")
    refresh_candidates(look)
    if request.app.state.settings.agent_mode == "gemini":
        profile = await profile_for(store, uid)
        note = await request.app.state.agents.run(
            create_styling_agent(request.app.state.settings),
            uid,
            {"look": look.model_dump(mode="json"), "profile": profile.model_dump()},
            Explanation,
        )
        look.styling_note = note.summary
    look.status = "assembled"
    return await save_look(store, uid, look)
