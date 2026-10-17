import asyncio

import pytest
from pydantic import ValidationError

from app.agents.food_agent import create_extraction_agent, create_report_agent
from app.agents.runtime import AgentRuntime
from app.agents.schemas import Explanation
from app.auth import current_user
from app.config import Settings
from app.memory.store import MemoryStore
from app.schemas import ChecklistItem, Look, LookBrief
from app.tools.budget import allocate_budget
from app.tools.food import split_label


def extract(client, text="Ingredients: milk powder, wheat flour, E102. May contain: peanuts."):
    response = client.post("/api/food/extract", json={"text": text, "product_name": "Test label"})
    assert response.status_code == 201, response.text
    return response.json()


def create_look(client, budget=600000):
    response = client.post(
        "/api/clothes/looks", json={"occasion": "Mehendi", "total_budget_minor": budget}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_food_confirmation_report_and_followup(client):
    assert client.put("/api/profile", json={"allergies": ["milk", "peanut"]}).status_code == 200
    scan = extract(client)
    assert scan["status"] == "awaiting_confirmation"
    assert scan["may_contain"] == ["peanuts"]
    path = f"/api/food/scans/{scan['id']}"
    assert client.post(path + "/ask", json={"question": "What was found?"}).status_code == 409
    body = {"ingredients": ["milk powder", "wheat flour", "E102"], "may_contain": ["peanuts"]}
    assert client.post(path + "/analyze", json=body).status_code == 422
    assert client.post(path + "/analyze", json=body | {"confirmed": False}).status_code == 422
    response = client.post(path + "/analyze", json=body | {"confirmed": True})
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert {(a["allergen"], a["type"]) for a in report["allergy_alerts"]} == {
        ("milk", "contains"),
        ("peanut", "may_contain"),
    }
    assert len(report["regulatory_alerts"]) == 3
    assert all(
        a["status"] == "unknown" and not a["verified"] and a["source_url"] is None
        for a in report["regulatory_alerts"]
    )
    assert "safe" not in report["summary"].lower()
    assert client.get(path).json()["status"] == "reported"
    assert client.post(path + "/ask", json={"question": "What was found?"}).json()["mode"] == "demo"


def test_confirmation_uses_edited_text(client):
    client.put("/api/profile", json={"allergies": ["milk"]})
    scan = extract(client)
    response = client.post(
        f"/api/food/scans/{scan['id']}/analyze",
        json={"confirmed": True, "ingredients": ["rice", "water"]},
    )
    assert response.json()["report"]["allergy_alerts"] == []


def test_negative_inputs_and_placeholder_integrations(client):
    assert client.post("/api/food/extract", json={"text": "   "}).status_code == 422
    assert (
        client.post(
            "/api/food/extract", json={"source": "barcode", "barcode": "12345678"}
        ).status_code
        == 501
    )
    assert (
        client.post(
            "/api/food/extract/photo", files={"image": ("label.txt", b"text", "text/plain")}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/food/extract/photo", files={"image": ("label.png", b"placeholder", "image/png")}
        ).status_code
        == 501
    )


def test_compound_label_parser():
    ingredients, contains, traces = split_label(
        "Ingredients: chocolate (sugar, cocoa), oats. Contains: milk. May contain: peanuts."
    )
    assert ingredients == ["chocolate (sugar, cocoa)", "oats"]
    assert contains == ["milk"] and traces == ["peanuts"]


def test_look_confirmation_lock_swap_and_assembly(client):
    look = create_look(client)
    path = f"/api/clothes/looks/{look['id']}"
    assert client.post(path + "/assemble").status_code == 409
    assert client.post(path + "/items/unknown", json={"action": "lock"}).status_code == 409
    response = client.post(
        path + "/checklist",
        json={
            "confirmed": True,
            "items": [{"category": "outfit"}, {"category": "footwear", "status": "owned"}],
        },
    )
    assert response.status_code == 200, response.text
    look = response.json()
    item = look["items"][0]
    assert item["budget_cap_minor"] == 600000
    item_path = path + f"/items/{item['id']}"
    assert (
        client.post(item_path, json={"action": "lock", "product_id": "forged"}).status_code == 422
    )
    look = client.post(
        item_path, json={"action": "lock", "product_id": item["candidates"][0]["id"]}
    ).json()
    assert look["total_spent_minor"] == 180000
    assert look["remaining_budget_minor"] == 420000
    assert look["items"][1]["status"] == "owned"
    assert client.post(path + "/assemble").json()["status"] == "assembled"
    look = client.post(item_path, json={"action": "swap"}).json()
    assert look["status"] == "shopping" and look["total_spent_minor"] == 0
    assert look["items"][0]["budget_cap_minor"] == 600000
    assert client.post(path + "/assemble").status_code == 409


def test_budget_caps_exclude_unaffordable_products(client):
    look = create_look(client, 100)
    look = client.post(
        f"/api/clothes/looks/{look['id']}/checklist",
        json={"confirmed": True, "items": [{"category": "outfit"}, {"category": "earrings"}]},
    ).json()
    assert all(not item["candidates"] for item in look["items"])
    assert sum(item["budget_cap_minor"] for item in look["items"]) == 100


def test_checklist_validation(client):
    look = create_look(client)
    path = f"/api/clothes/looks/{look['id']}/checklist"
    assert (
        client.post(
            path,
            json={"confirmed": True, "items": [{"category": "outfit"}, {"category": "outfit"}]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            path, json={"confirmed": True, "items": [{"category": "outfit", "status": "removed"}]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/clothes/looks", json={"occasion": "Dinner", "total_budget_minor": -1}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("budget", [1, 2, 99, 10001, 999999])
def test_allocation_preserves_every_paisa(budget):
    look = Look(
        brief=LookBrief(occasion="Dinner", total_budget_minor=budget),
        items=[ChecklistItem(category=c) for c in ("outfit", "footwear", "earrings", "bangles")],
    )
    allocate_budget(look)
    assert sum(item.budget_cap_minor for item in look.items) == budget
    assert all(item.budget_cap_minor >= 0 for item in look.items)


def test_record_ownership(client):
    scan = extract(client)
    look = create_look(client)
    client.app.dependency_overrides[current_user] = lambda: "another-user"
    assert client.get(f"/api/food/scans/{scan['id']}").status_code == 404
    assert client.get(f"/api/clothes/looks/{look['id']}").status_code == 404
    assert client.get("/api/food/scans").json() == []
    assert client.get("/api/clothes/looks").json() == []


def test_store_returns_copies():
    async def check():
        store = MemoryStore()
        await store.put("a", "scans", "s", {"ingredients": ["oats"]})
        record = await store.get("a", "scans", "s")
        record["ingredients"].append("milk")
        assert (await store.get("a", "scans", "s"))["ingredients"] == ["oats"]
        assert await store.get("b", "scans", "s") is None

    asyncio.run(check())


def test_adk_factories_and_prompt_gate():
    settings = Settings(_env_file=None, agent_mode="gemini", google_api_key="test-key-not-real")
    assert create_extraction_agent(settings).output_schema.__name__ == "ExtractedLabel"
    agent = create_report_agent(settings)
    assert agent.model == settings.gemini_model
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        asyncio.run(AgentRuntime(settings).run(agent, "test-user", {}, Explanation))
    assert error.value.status_code == 501


def test_production_rejects_demo_auth_and_ephemeral_storage():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")


def test_unknown_api_is_not_spa_html(client):
    assert client.get("/api/not-a-route").status_code == 404
    assert client.get("/api/health").json()["agent_mode"] == "demo"


def test_built_spa_routes_and_static_boundary(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>IntentCart test</title>")
    (dist / "icon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("not public")
    settings = Settings(_env_file=None, frontend_dist=dist)
    with TestClient(create_app(settings)) as client:
        for route in ("/", "/food", "/clothes", "/profile"):
            response = client.get(route)
            assert response.status_code == 200
            assert "IntentCart test" in response.text
        assert client.get("/icon.svg").status_code == 200
        assert client.get("/missing.js").status_code == 404
        assert client.get("/%2e%2e/secret.txt").status_code == 404
        assert client.get("/api/missing").status_code == 404
