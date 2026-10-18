from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.agents.food_agent import (
    create_extraction_agent,
    create_followup_agent,
)
from app.agents.food_pipeline import acceptable_prose, report_sources
from app.agents.schemas import ExtractedLabel, FollowUp
from app.auth import current_user
from app.dependencies import get_store, owned_record, profile_for
from app.memory.store import Store
from app.schemas import Answer, ConfirmIngredients, ExtractRequest, ProductLabel, Question, Scan
from app.tools.food import split_label
from app.tools.open_food_facts import lookup_barcode

router = APIRouter(prefix="/food", tags=["food"])


async def save_scan(store, uid, scan):
    await store.put(uid, "scans", scan.id, scan.model_dump(mode="json"))
    return scan


@router.post("/extract", response_model=Scan, status_code=201)
async def extract(
    body: ExtractRequest,
    request: Request,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    source_url = None
    ingredients, contains, traces = split_label(body.text)
    name = body.product_name
    if body.source == "barcode":
        product = await lookup_barcode(body.barcode, request.app.state.settings)
        name = product.get("product_name") or name
        ingredients, contains, traces = split_label(product["ingredients_text"])
        contains += [tag.split(":", 1)[-1] for tag in product.get("allergens_tags", [])]
        traces += [tag.split(":", 1)[-1] for tag in product.get("traces_tags", [])]
        source_url = f"https://world.openfoodfacts.org/product/{body.barcode}"
    if not ingredients:
        raise HTTPException(422, "No ingredients found. Enter the ingredient list.")
    scan = Scan(
        product=ProductLabel(
            name=name, source=body.source, barcode=body.barcode, source_url=source_url
        ),
        ingredients=ingredients,
        contains=contains,
        may_contain=traces,
    )
    return await save_scan(store, uid, scan)


@router.post("/extract/photo", response_model=Scan, status_code=201)
async def extract_photo(
    request: Request,
    image: UploadFile = File(...),
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "Use a JPEG, PNG or WebP label photo.")
    data = await image.read(5 * 1024 * 1024 + 1)
    await image.close()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Choose a non-empty photo smaller than 5 MB.")
    settings = request.app.state.settings
    parsed = await request.app.state.agents.run(
        create_extraction_agent(settings),
        uid,
        {"task": "extract_label"},
        ExtractedLabel,
        image=data,
        mime=image.content_type,
    )
    if parsed.needs_clearer_image or not parsed.ingredients:
        raise HTTPException(422, "The label could not be read. Try a clearer photo or typed text.")
    scan = Scan(
        product=ProductLabel(name=parsed.product_name, source="photo"),
        ingredients=parsed.ingredients,
        contains=parsed.contains,
        may_contain=parsed.may_contain,
    )
    return await save_scan(store, uid, scan)


@router.get("/scans", response_model=list[Scan])
async def list_scans(uid: str = Depends(current_user), store: Store = Depends(get_store)):
    return await store.list(uid, "scans")


@router.get("/scans/{scan_id}", response_model=Scan)
async def get_scan(
    scan_id: str, uid: str = Depends(current_user), store: Store = Depends(get_store)
):
    return await owned_record(store, uid, "scans", scan_id)


@router.post("/scans/{scan_id}/analyze", response_model=Scan)
async def analyze(
    scan_id: str,
    body: ConfirmIngredients,
    request: Request,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    scan = Scan.model_validate(await owned_record(store, uid, "scans", scan_id))
    profile = await profile_for(store, uid)
    report = await request.app.state.food_pipeline.analyze(scan, body, profile, uid)
    scan.ingredients, scan.contains, scan.may_contain = (
        body.ingredients,
        body.contains,
        body.may_contain,
    )
    scan.report, scan.status = report, "reported"
    return await save_scan(store, uid, scan)


@router.post("/scans/{scan_id}/ask", response_model=Answer)
async def ask(
    scan_id: str,
    body: Question,
    request: Request,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
):
    scan = Scan.model_validate(await owned_record(store, uid, "scans", scan_id))
    if not scan.report:
        raise HTTPException(409, "Confirm the ingredients and create a report first.")
    settings = request.app.state.settings
    if settings.agent_mode == "demo":
        return Answer(
            answer="Live follow-up is disabled. " + scan.report.summary,
            sources=sorted(report_sources(scan.report)),
            mode="demo",
        )
    profile = await profile_for(store, uid)
    allowed = report_sources(scan.report)
    food_profile = profile.model_dump(
        include={"age_group", "allergies", "diet", "country", "food_countries"}
    )
    result = await request.app.state.agents.run(
        create_followup_agent(settings),
        uid,
        {
            "question": body.question,
            "report": scan.report.model_dump(mode="json"),
            "profile": food_profile,
            "profile_changed": food_profile != scan.report.profile_context,
            "allowed_sources": sorted(allowed),
        },
        FollowUp,
    )
    if not acceptable_prose(result.answer):
        return Answer(
            answer="The saved evidence does not establish individual suitability. Review the findings and their source conditions above.",
            mode="gemini",
        )
    return Answer(
        answer=result.answer,
        sources=[url for url in result.sources if url in allowed],
        mode="gemini",
    )
