import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import ClientError
from pydantic import PrivateAttr

from app.auth import current_user
from app.clothes.discovery import Discovery
from app.clothes.pages import FetchResult
from app.clothes.service import LookError, LookService, shortlist
from app.config import Settings
from app.main import create_app
from app.memory.store import MemoryStore
from app.schemas import CatalogProduct, ChecklistChoice, ChecklistItem, LookBrief, PieceSpec

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def settings(**overrides):
    values = {
        "app_env": "test",
        "agent_mode": "demo",
        "stylist_agent_mode": "gemini",
        "stylist_search_enabled": True,
        "google_api_key": "test-not-real",
        "agent_session_backend": "memory",
        "artifact_backend": "memory",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class Scripted(BaseLlm):
    """A Gemini-named fake (built-in tools require a gemini model name)."""

    model: str = "gemini-scripted"
    _requests: list = PrivateAttr(default_factory=list)
    _handler: object = PrivateAttr(default=None)

    async def generate_content_async(self, llm_request, stream=False):
        self._requests.append(llm_request.model_copy(deep=True))
        yield self._handler(llm_request, len(self._requests))


def text(value, grounding=None):
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=value)]),
        grounding_metadata=grounding,
    )


def call(name, **args):
    return LlmResponse(
        content=types.Content(
            role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
        )
    )


def last_text(request) -> str:
    for content in reversed(request.contents):
        for part in content.parts or []:
            if part.text:
                return part.text
    return ""


def tool_responses(request) -> list[dict]:
    return [
        part.function_response.response
        for content in request.contents
        for part in content.parts or []
        if part.function_response
    ]


# ---------------------------------------------------------------------------- pages
def html(title, price, currency="INR", image="https://img.example/p.jpg"):
    return (
        f'<html><head><meta property="og:title" content="{title}">'
        f'<meta property="og:price:amount" content="{price}">'
        f'<meta property="og:price:currency" content="{currency}">'
        f'<meta property="og:image" content="{image}"></head></html>'
    )


PAGES = {
    "https://indie.example.in/products/silver-jhumka": html("Oxidised silver jhumkas", "650"),
    "https://www.myntra.com/earrings/1/buy": html("Gold-tone drop earrings", "450"),
    "https://craft.example.in/products/kundan-studs": html("Kundan studs", "500"),
    "https://www.myntra.com/lehenga/2/buy": html("Mint lehenga set", "3000"),
    "https://atelier.example.in/products/mirror-lehenga": html("Mirror work lehenga", "9000"),
}
REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"


async def fake_fetch(url):
    if url == REDIRECT:
        final = "https://craft.example.in/products/kundan-studs"
        return FetchResult(True, url, final, 200, "text/html", PAGES[final])
    if url in PAGES:
        return FetchResult(True, url, url, 200, "text/html", PAGES[url])
    return FetchResult(False, url, error="http_404")


def discovery_model():
    model = Scripted()

    def handle(request, _):
        instruction = str(request.config.system_instruction)
        payload = json.loads(last_text(request))
        if "find individual product pages" in instruction:
            category = payload["item"]["category"]
            if category == "footwear":
                raise ClientError(429, {"error": {"message": "private-provider-payload"}})
            urls = {
                "earrings": [
                    "https://indie.example.in/products/silver-jhumka",
                    "https://www.myntra.com/earrings/1/buy",
                    "https://made-up.example.in/products/hallucinated",
                ],
                "outfit": [
                    "https://www.myntra.com/lehenga/2/buy",
                    "https://atelier.example.in/products/mirror-lehenga",
                ],
            }[category]
            grounding = types.GroundingMetadata(
                grounding_chunks=[
                    types.GroundingChunk(web=types.GroundingChunkWeb(uri=REDIRECT, title="craft"))
                ]
            ) if category == "earrings" else None
            return text(json.dumps({"products": [{"url": u} for u in urls]}), grounding)
        if "score product candidates" in instruction:
            scores = []
            for candidate in payload["candidates"]:
                # The marketplace scores highest, so the small-business slot rule is exercised.
                score = 90 if "Gold-tone" in candidate["title"] else 60
                if payload["locked_pieces"]:
                    score = 99 if "Mint" in candidate["title"] else 10
                scores.append({"id": candidate["id"], "score": score, "reason": "Fits the brief."})
            return text(json.dumps({"scores": scores}))
        raise AssertionError("unexpected agent")

    model._handler = handle
    return model


def test_discovery_workflow_verifies_ranks_and_isolates_failures():
    async def scenario():
        looks = LookService(MemoryStore())
        discovery = Discovery(settings(), looks, fetch=fake_fetch)
        discovery.search_model = discovery.rank_model = model = discovery_model()
        brief = LookBrief(occasion="Mehendi", total_budget_minor=1_000_000)
        look = await looks.create_for_session("user-a", "session-1", brief)
        await looks.propose_checklist(
            "user-a", look.id,
            [PieceSpec(category="outfit", target="mint lehenga"),
             PieceSpec(category="earrings", target="silver jhumkas"),
             PieceSpec(category="footwear", target="juttis")],
        )
        look = await looks.confirm_checklist(
            "user-a", look.id,
            [ChecklistChoice(category=c) for c in ("outfit", "earrings", "footwear")],
        )
        started = await discovery.start("user-a", look.id)
        assert len(started) == 3
        searching = await looks.get("user-a", look.id)
        assert {i.discovery for i in searching.items} == {"searching"}
        await discovery.wait_idle()
        look = await looks.get("user-a", look.id)
        items = {i.category: i for i in look.items}

        earrings = items["earrings"]
        assert earrings.discovery == "ready", earrings.discovery_note
        titles = [p.title for p in earrings.candidates]
        # Grounding redirect resolved; hallucinated URL dropped; prices from pages only.
        assert "Kundan studs" in titles and len(earrings.pool) == 3
        assert all(p.url and "hallucinated" not in p.url for p in earrings.pool)
        assert {p.price_minor for p in earrings.pool} == {65000, 45000, 50000}
        labels = {p.title: p.seller_label for p in earrings.pool}
        assert labels["Gold-tone drop earrings"] == "marketplace"
        assert labels["Oxidised silver jhumkas"] == "independent"
        assert earrings.candidates[0].match_reason == "Fits the brief."

        outfit = items["outfit"]
        # ₹9,000 is above the outfit cap (₹8,181) so it stays in the pool, not the shortlist.
        assert [p.title for p in outfit.candidates] == ["Mint lehenga set"]
        assert len(outfit.pool) == 2

        footwear = items["footwear"]
        assert footwear.discovery == "failed" and not footwear.pool

        # Locking re-ranks the remaining open items against the locked piece.
        lehenga = outfit.candidates[0]
        await looks.item_action("user-a", look.id, outfit.id, "lock", lehenga.id)
        await discovery.rescore("user-a", look.id)
        await discovery.wait_idle()
        ranked = [r for r in model._requests if "score product candidates" in str(r.config.system_instruction)]
        assert "Mint lehenga set" in last_text(ranked[-1])
        return look

    asyncio.run(scenario())


def test_discovery_disabled_marks_items_honestly():
    async def scenario():
        looks = LookService(MemoryStore())
        discovery = Discovery(settings(stylist_search_enabled=False), looks)
        look = await looks.create_for_session(
            "u", "s", LookBrief(occasion="Haldi", total_budget_minor=500_000)
        )
        await looks.propose_checklist("u", look.id, [PieceSpec(category="outfit")])
        await looks.confirm_checklist("u", look.id, [ChecklistChoice(category="outfit")])
        assert await discovery.start("u", look.id) == []
        look = await looks.get("u", look.id)
        assert look.items[0].discovery == "failed"
        assert "not enabled" in look.items[0].discovery_note

    asyncio.run(scenario())


# ---------------------------------------------------------------------------- shortlist
def product(pid, price, label, score=50, source="live"):
    return CatalogProduct(
        id=pid, category="earrings", title=pid, price_minor=price, source=source,
        seller_label=label, style_score=score,
    )


def test_shortlist_budget_rejections_and_small_business_slot():
    item = ChecklistItem(category="earrings", budget_cap_minor=60_000)
    item.pool = [
        product("m1", 40_000, "marketplace", 95),
        product("m2", 41_000, "marketplace", 94),
        product("m3", 42_000, "marketplace", 93),
        product("m4", 43_000, "marketplace", 92),
        product("indie", 50_000, "independent", 40),
        product("pricey", 90_000, "independent", 99),
        product("mine", 55_000, "unknown", source="user"),
    ]
    item.rejected_ids = ["m1"]
    ids = [p.id for p in shortlist(item, "prefer")]
    assert ids[0] == "mine" and "indie" in ids and "pricey" not in ids and "m1" not in ids
    assert len(ids) == 4
    assert [p.id for p in shortlist(item, "only")] == ["mine", "indie"]
    assert "indie" not in [p.id for p in shortlist(item, "off")]
    # Clear mismatches (e.g. a bulk gift pack) are not shown, even when nothing else fits.
    item.pool = [product("bulk", 10_000, "independent", 20)]
    item.rejected_ids = []
    assert shortlist(item, "prefer") == []


def test_lock_requires_current_candidate_and_custom_categories_get_budget():
    async def scenario():
        looks = LookService(MemoryStore())
        look = await looks.create_for_session(
            "u", "s", LookBrief(occasion="Sangeet", total_budget_minor=300_000)
        )
        await looks.propose_checklist(
            "u", look.id, [PieceSpec(category="outfit"), PieceSpec(category="dupatta")]
        )
        look = await looks.confirm_checklist(
            "u", look.id, [ChecklistChoice(category="outfit"), ChecklistChoice(category="dupatta")]
        )
        dupatta = next(i for i in look.items if i.category == "dupatta")
        assert dupatta.budget_cap_minor > 0
        assert sum(i.budget_cap_minor for i in look.items) == 300_000
        with pytest.raises(LookError):
            await looks.item_action("u", look.id, dupatta.id, "lock", "p_invented")
        with pytest.raises(LookError):
            await looks.update_brief("u", look.id, {"total_budget_minor": -5})

    asyncio.run(scenario())


# ---------------------------------------------------------------------------- coordinator
@pytest.fixture
def stylist():
    with TestClient(create_app(settings())) as client:
        model = Scripted()
        client.app.state.conversations.runner("stylist").agent.model = model
        yield client, model


def new_session(client):
    response = client.post("/api/agents/stylist/sessions")
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client, session_id, text_value, **extra):
    return client.post(
        f"/api/agents/stylist/sessions/{session_id}/messages",
        json={"text": text_value, "request_id": str(uuid4()), **extra},
    )


def test_coordinator_builds_the_look_through_tools(stylist):
    client, model = stylist
    script = {
        1: call("save_brief", occasion="Sister's mehendi", total_budget_inr=6000, colours=["mint"]),
        2: call("propose_checklist", items=[
            {"category": "outfit", "target": "mint lehenga with mirror work"},
            {"category": "Earrings", "target": "oxidised silver jhumkas"},
        ]),
        3: text("Your checklist is on the board."),
        4: call("select_product", category="outfit", product_id="p_invented"),
        5: text("Please confirm the checklist first."),
    }
    model._handler = lambda request, n: script[n]
    session_id = new_session(client)
    response = send(client, session_id, "Mehendi look, budget 6000")
    assert response.status_code == 200, response.text
    conversation = response.json()
    look_id = conversation["look_id"]
    assert look_id and conversation["messages"][-1]["text"] == "Your checklist is on the board."

    look = client.get(f"/api/clothes/looks/{look_id}").json()
    assert look["mode"] == "agent" and look["session_id"] == session_id
    assert look["status"] == "awaiting_checklist"
    assert look["brief"]["total_budget_minor"] == 600000 and look["brief"]["colours"] == ["mint"]
    assert [(i["category"], i["target"]) for i in look["items"]] == [
        ("outfit", "mint lehenga with mirror work"), ("earrings", "oxidised silver jhumkas"),
    ]
    assert "Current look board" in str(model._requests[2].config.system_instruction)
    assert "mint lehenga" in str(model._requests[2].config.system_instruction)

    # The model cannot lock anything that is not a confirmed, server-provided candidate.
    assert send(client, session_id, "Lock the lehenga").status_code == 200
    assert "Confirm your checklist first." in str(tool_responses(model._requests[4]))
    assert client.get(f"/api/clothes/looks/{look_id}").json()["status"] == "awaiting_checklist"

    # Another user can see neither the look nor the conversation.
    client.app.dependency_overrides[current_user] = lambda: "someone-else"
    assert client.get(f"/api/clothes/looks/{look_id}").status_code == 404


def test_reference_attachments_are_validated_owned_and_analysed(stylist):
    client, model = stylist
    analysis_model = Scripted()
    seen = {}

    def analyse(request, _):
        seen["image"] = any(
            part.inline_data and part.inline_data.mime_type == "image/png"
            for content in request.contents for part in content.parts or []
        )
        return text(json.dumps({
            "summary": "Mint lehenga with mirror work.", "palette": ["mint"],
            "pieces": [{"category": "outfit", "target": "mint mirror-work lehenga"}],
        }))

    analysis_model._handler = analyse
    client.app.state.studio.models["reference_analysis"] = analysis_model
    script = {
        1: call("save_brief", occasion="Mehendi", total_budget_inr=8000),
        2: call("analyze_reference", request="recreate this with cheaper accessories"),
        3: text("I can see a mint lehenga."),
    }
    model._handler = lambda request, n: script[n]
    session_id = new_session(client)
    url = f"/api/agents/stylist/sessions/{session_id}/attachments"
    assert client.post(url, files={"image": ("x.png", b"not an image", "image/png")}).status_code == 415
    assert client.post(url, files={"image": ("x.gif", PNG, "image/gif")}).status_code == 415
    upload = client.post(url, files={"image": ("look.png", PNG, "image/png")})
    assert upload.status_code == 201, upload.text
    name = upload.json()["name"]
    assert send(client, session_id, "Recreate this", attachments=["ref-000000000000.png"]).status_code == 422

    response = send(client, session_id, "Recreate this look", attachments=[name])
    assert response.status_code == 200, response.text
    user_message = response.json()["messages"][0]
    assert user_message["attachments"] == [name]
    assert "attached 1 reference image" in str(model._requests[0].config.system_instruction)
    assert seen["image"] is True
    look = client.get(f"/api/clothes/looks/{response.json()['look_id']}").json()
    assert look["analysis"]["pieces"][0]["target"] == "mint mirror-work lehenga"
    assert look["references"] == [name]

    artifact = f"/api/agents/stylist/sessions/{session_id}/artifacts/{name}"
    assert client.get(artifact).content == PNG
    assert client.get(f"/api/agents/stylist/sessions/{session_id}/artifacts/..%2Fsecret").status_code == 404
    client.app.dependency_overrides[current_user] = lambda: "someone-else"
    assert client.get(artifact).status_code == 404


def test_provider_errors_are_redacted_from_persisted_events(stylist):
    client, model = stylist

    def fail(request, n):
        raise ClientError(500, {"error": {"message": "private-provider-payload"}})

    model._handler = fail
    session_id = new_session(client)
    assert send(client, session_id, "Hello").status_code >= 500

    async def events():
        service = client.app.state.conversations
        session = await service.get_session("stylist", "local-demo-user", session_id)
        return str([event.model_dump() for event in session.events])

    dumped = asyncio.run(events())
    assert "private-provider-payload" not in dumped


class Gated(Scripted):
    """Search responses wait for a gate, so a second job can overtake the first."""

    _gates: list = PrivateAttr(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        self._requests.append(llm_request.model_copy(deep=True))
        instruction = str(llm_request.config.system_instruction)
        if "find individual product pages" in instruction:
            gate = asyncio.Event()
            self._gates.append(gate)
            await gate.wait()
            url = (
                "https://www.myntra.com/lehenga/2/buy"
                if len(self._gates) == 1
                else "https://atelier.example.in/products/mirror-lehenga"
            )
            yield text(json.dumps({"products": [{"url": url}]}))
        else:
            payload = json.loads(last_text(llm_request))
            yield text(json.dumps({"scores": [
                {"id": c["id"], "score": 80, "reason": "ok"} for c in payload["candidates"]
            ]}))


def test_newer_search_owns_the_item_and_stale_jobs_cannot_overwrite_it():
    async def scenario():
        looks = LookService(MemoryStore())
        discovery = Discovery(settings(), looks, fetch=fake_fetch)
        discovery.search_model = discovery.rank_model = model = Gated()
        look = await looks.create_for_session(
            "u", "s", LookBrief(occasion="Mehendi", total_budget_minor=2_000_000)
        )
        await looks.propose_checklist("u", look.id, [PieceSpec(category="outfit")])
        look = await looks.confirm_checklist("u", look.id, [ChecklistChoice(category="outfit")])
        item_id = look.items[0].id
        await discovery.start("u", look.id)
        while len(model._gates) < 1:
            await asyncio.sleep(0.01)
        await discovery.start("u", look.id, [item_id], request="more mirror work")
        while len(model._gates) < 2:
            await asyncio.sleep(0.01)
        model._gates[0].set()  # the stale job finishes first
        await asyncio.sleep(0.2)
        item = (await looks.get("u", look.id)).items[0]
        assert item.discovery == "searching" and not item.pool
        model._gates[1].set()
        await discovery.wait_idle()
        item = (await looks.get("u", look.id)).items[0]
        assert item.discovery == "ready"
        assert [p.title for p in item.pool] == ["Mirror work lehenga"]

    asyncio.run(scenario())
