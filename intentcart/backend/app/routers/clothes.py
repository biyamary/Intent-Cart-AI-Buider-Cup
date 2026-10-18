from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.schemas import ParsedBrief
from app.agents.stylist_agent import create_brief_agent
from app.auth import current_user
from app.clothes.discovery import Discovery
from app.clothes.service import LookError, LookService, find_item
from app.clothes.studio import Studio
from app.clothes.tools import verify_link
from app.dependencies import get_store, profile_for
from app.memory.store import Store
from app.schemas import (
    AddItem,
    AddProductLink,
    Alternatives,
    ChecklistItem,
    ConfirmChecklist,
    ItemAction,
    Look,
    LookBrief,
)
from app.tools.budget import WEIGHTS

router = APIRouter(prefix="/clothes", tags=["clothes"])


def looks(request: Request) -> LookService:
    return request.app.state.looks


def discovery(request: Request) -> Discovery:
    return request.app.state.discovery


def studio(request: Request) -> Studio:
    return request.app.state.studio


async def run(action):
    try:
        return await action
    except LookError as error:
        raise HTTPException(error.status, error.detail) from None


@router.post("/looks", response_model=Look, status_code=201)
async def create_look(
    brief: LookBrief,
    request: Request,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
    service: LookService = Depends(looks),
):
    """Sample board look (seed catalog). Agent looks are created by the stylist."""
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
    return await service.create(uid, look)


@router.get("/looks", response_model=list[Look])
async def list_looks(uid: str = Depends(current_user), service: LookService = Depends(looks)):
    return await service.list_looks(uid)


@router.get("/looks/{look_id}", response_model=Look)
async def get_look(
    look_id: str, uid: str = Depends(current_user), service: LookService = Depends(looks)
):
    return await run(service.get(uid, look_id))


@router.post("/looks/{look_id}/checklist", response_model=Look)
async def confirm_checklist(
    look_id: str,
    body: ConfirmChecklist,
    uid: str = Depends(current_user),
    service: LookService = Depends(looks),
    jobs: Discovery = Depends(discovery),
):
    look = await run(service.confirm_checklist(uid, look_id, body.items))
    if look.mode == "agent":
        await jobs.start(uid, look.id)
        look = await service.get(uid, look.id)
    return look


@router.post("/looks/{look_id}/items", response_model=Look, status_code=201)
async def add_item(
    look_id: str,
    body: AddItem,
    uid: str = Depends(current_user),
    service: LookService = Depends(looks),
    jobs: Discovery = Depends(discovery),
):
    look = await run(service.add_item(uid, look_id, body.category, body.target))
    if look.mode == "agent" and look.status == "shopping":
        await jobs.start(uid, look.id, [find_item(look, body.category).id])
        look = await service.get(uid, look.id)
    return look


@router.post("/looks/{look_id}/items/{item_id}", response_model=Look)
async def change_item(
    look_id: str,
    item_id: str,
    body: ItemAction,
    uid: str = Depends(current_user),
    service: LookService = Depends(looks),
    jobs: Discovery = Depends(discovery),
):
    look = await run(service.item_action(uid, look_id, item_id, body.action, body.product_id))
    if look.mode == "agent":
        if body.action == "lock":
            await jobs.rescore(uid, look.id)
        elif body.action in {"swap", "reopen", "reject"}:
            item = find_item(look, item_id)
            if len(item.candidates) < 2 and item.discovery != "searching":
                await jobs.start(uid, look.id, [item.id])
                look = await service.get(uid, look.id)
    return look


@router.post("/looks/{look_id}/items/{item_id}/alternatives", response_model=Look)
async def alternatives(
    look_id: str,
    item_id: str,
    body: Alternatives,
    uid: str = Depends(current_user),
    service: LookService = Depends(looks),
    jobs: Discovery = Depends(discovery),
):
    look = await run(service.get(uid, look_id))
    item = await run(_open_agent_item(look, item_id))
    started = await jobs.start(
        uid, look.id, [item.id], request=body.request, max_price_minor=body.max_price_minor
    )
    if not started:
        raise HTTPException(503, "Live product search is not available right now.")
    return await service.get(uid, look.id)


@router.post("/looks/{look_id}/items/{item_id}/link", response_model=Look)
async def add_link(
    look_id: str,
    item_id: str,
    body: AddProductLink,
    uid: str = Depends(current_user),
    service: LookService = Depends(looks),
):
    look = await run(service.get(uid, look_id))
    item = await run(_open_agent_item(look, item_id))
    product = await run(verify_link(item.category, body.url, body.price_minor))
    return await run(service.add_user_product(uid, look.id, item.id, product))


@router.post("/looks/{look_id}/discover", response_model=Look)
async def discover(
    look_id: str,
    uid: str = Depends(current_user),
    service: LookService = Depends(looks),
    jobs: Discovery = Depends(discovery),
):
    look = await run(service.get(uid, look_id))
    if look.mode != "agent" or look.status != "shopping":
        raise HTTPException(409, "Confirm the checklist of a stylist look first.")
    retry = [i.id for i in look.items if i.status == "open" and i.discovery != "searching"]
    await jobs.start(uid, look.id, retry)
    return await service.get(uid, look.id)


@router.post("/looks/{look_id}/assemble", response_model=Look)
async def assemble(
    look_id: str,
    request: Request,
    uid: str = Depends(current_user),
    service: LookService = Depends(looks),
    writer: Studio = Depends(studio),
):
    look = await run(service.get(uid, look_id))
    if look.status == "awaiting_checklist" or any(i.status == "open" for i in look.items):
        raise HTTPException(409, "Resolve each checklist item before assembling your look.")
    note = None
    settings = request.app.state.settings
    if (settings.agent_mode == "gemini" or (look.mode == "agent" and settings.stylist_mode == "gemini")):
        try:
            note = await writer.styling_note(look) or None
        except Exception:  # noqa: BLE001 -- the styling note is optional
            note = None
    return await run(service.assemble(uid, look.id, note))


async def _open_agent_item(look: Look, item_id: str):
    if look.mode != "agent":
        raise LookError(409, "Live product actions are only available for stylist looks.")
    item = find_item(look, item_id)
    if item.status != "open":
        raise LookError(409, "Swap or reopen this item first.")
    return item
