import asyncio
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.genai import types
from google.genai.errors import ClientError
from pydantic import PrivateAttr

from app.agents.conversation_schemas import ChatRequest
from app.agents.conversations import ConversationService
from app.auth import current_user
from app.config import Settings
from app.main import create_app
from app.schemas import Profile


class FakeGemini(BaseLlm):
    """Exercise the real ADK Runner/session pipeline without external requests."""

    model: str = "gemini-test"
    _requests: list = PrivateAttr(default_factory=list)
    _failure: Exception | None = PrivateAttr(default=None)

    async def generate_content_async(self, llm_request, stream=False):
        self._requests.append(llm_request.model_copy(deep=True))
        if self._failure:
            raise self._failure
        if len(self._requests) == 1:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(text="Private model reasoning", thought=True),
                        types.Part(
                            text="For your sister's mehendi, what budget and outfit style do you prefer?"
                        ),
                    ],
                )
            )
        else:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text="For the mehendi, consider this green kurta option. Check the retailer's current price."
                        )
                    ],
                ),
                grounding_metadata=types.GroundingMetadata(
                    web_search_queries=["green kurta India under 6000"],
                    grounding_chunks=[
                        types.GroundingChunk(
                            web=types.GroundingChunkWeb(
                                uri="https://example.com/kurta", title="Example retailer"
                            )
                        )
                    ],
                    grounding_supports=[
                        types.GroundingSupport(
                            segment=types.Segment(
                                text="green kurta option", start_index=32, end_index=50
                            ),
                            grounding_chunk_indices=[0],
                        )
                    ],
                    search_entry_point=types.SearchEntryPoint(
                        rendered_content='<div><a href="https://www.google.com/search?q=kurta" target="_blank">Search kurta</a></div>'
                    ),
                ),
            )


class SlowGemini(FakeGemini):
    _delay: float = PrivateAttr(default=0.08)

    async def generate_content_async(self, llm_request, stream=False):
        await asyncio.sleep(self._delay)
        async for response in super().generate_content_async(llm_request, stream=stream):
            yield response


def settings(**overrides):
    overrides.setdefault("stylist_search_enabled", False)
    return Settings(
        _env_file=None,
        app_env="test",
        agent_mode="demo",
        stylist_agent_mode="gemini",
        google_api_key="test-not-real",
        agent_session_backend="memory",
        **overrides,
    )


@pytest.fixture
def chat_client(request):
    with TestClient(
        create_app(settings(stylist_search_enabled=getattr(request, "param", False)))
    ) as client:
        model = FakeGemini()
        client.app.state.conversations.runner("stylist").agent.model = model
        yield client, model


def tool_names(request) -> set[str]:
    return {
        declaration.name
        for tool in request.config.tools or []
        for declaration in tool.function_declarations or []
    }


def new_session(client):
    response = client.post("/api/agents/stylist/sessions")
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client, session_id, text, request_id=None):
    return client.post(
        f"/api/agents/stylist/sessions/{session_id}/messages",
        json={"text": text, "request_id": request_id or str(uuid4())},
    )


def wait_for_turn(client, agent_id, session_id, request_id, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/agents/{agent_id}/sessions/{session_id}/turns/{request_id}")
        assert response.status_code == 200, response.text
        turn = response.json()
        if turn["status"] in {"succeeded", "failed"}:
            return turn
        time.sleep(0.01)
    raise AssertionError("turn did not finish")


@pytest.mark.parametrize("chat_client", [True], indirect=True)
def test_real_adk_runner_remembers_turns_and_preserves_grounding(chat_client):
    client, model = chat_client
    client.put(
        "/api/profile",
        json={
            "country": "India",
            "allergies": ["private-allergy"],
            "style": {"colours": ["green"]},
        },
    )
    session_id = new_session(client)
    response = send(client, session_id, "I want an outfit for my sister's mehendi")
    assert response.status_code == 200, response.text
    assert len(response.json()["messages"]) == 2
    assert "Private model reasoning" not in str(response.json())
    response = send(client, session_id, "Budget INR 6000, a green kurta in India")
    assert response.status_code == 200, response.text
    messages = response.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[-1]["sources"] == [
        {"title": "Example retailer", "url": "https://example.com/kurta"}
    ]
    assert messages[-1]["citations"][0]["source_indices"] == [0]
    assert messages[-1]["search_queries"] == ["green kurta India under 6000"]
    assert "Search kurta" in messages[-1]["search_entry_point"]
    request = model._requests[-1]
    assert "sister's mehendi" in str(request.contents)
    assert "green" in str(request.config.system_instruction)
    assert "private-allergy" not in str(request)
    # Store search goes through the verified discovery workflow, not raw search in chat.
    assert "find_products" in tool_names(request)
    history = client.get("/api/agents/stylist/sessions").json()
    assert history[0]["id"] == session_id
    assert history[0]["title"].startswith("I want an outfit")


@pytest.mark.parametrize("chat_client", [False, True], indirect=True)
def test_search_setting_controls_tools_prompt_and_public_capabilities(chat_client):
    client, model = chat_client
    search_enabled = client.app.state.settings.stylist_search_enabled
    info = client.get("/api/agents").json()[0]
    assert info["enabled"] is True
    assert ("google_search" in info["capabilities"]) == search_enabled
    assert ("product_discovery" in info["capabilities"]) == search_enabled
    session_id = new_session(client)
    response = send(client, session_id, "Please search for a green mehendi outfit under INR 6000")
    assert response.status_code == 200, response.text
    request = model._requests[-1]
    names = tool_names(request)
    assert {"save_brief", "propose_checklist", "select_product"} <= names
    assert ({"find_products", "find_alternatives", "find_inspiration"} <= names) == search_enabled
    assert not any(tool.google_search is not None for tool in request.config.tools or [])
    instruction = str(request.config.system_instruction)
    assert f"Google Search is {'enabled' if search_enabled else 'disabled'}" in instruction
    assert "Current look: none yet" in instruction
    if not search_enabled:
        assert "Do not claim to search" in instruction
        assert not names & {"find_products", "find_alternatives", "find_inspiration"}


def test_idempotency_and_user_isolation(chat_client):
    client, model = chat_client
    session_id = new_session(client)
    request_id = str(uuid4())
    assert send(client, session_id, "Mehendi outfit", request_id).status_code == 200
    assert send(client, session_id, "Mehendi outfit", request_id).status_code == 200
    assert len(model._requests) == 1
    client.app.dependency_overrides[current_user] = lambda: "another-user"
    assert client.get(f"/api/agents/stylist/sessions/{session_id}").status_code == 404
    assert send(client, session_id, "Read that conversation").status_code == 404
    assert client.get("/api/agents/stylist/sessions").json() == []
    assert client.post("/api/agents/unknown-agent/sessions").status_code == 404


def test_disabled_agent_and_invalid_inputs(client, chat_client):
    assert client.post("/api/agents/stylist/sessions").status_code == 503
    assert client.post("/api/agents/food/sessions").status_code == 503
    agents = client.get("/api/agents").json()
    assert all(a["enabled"] is False for a in agents)
    live, model = chat_client
    session_id = new_session(live)
    assert send(live, session_id, "  ").status_code == 422
    assert send(live, session_id, "a" * 4001).status_code == 422
    assert send(live, session_id, "hello", "invalid-id").status_code == 422
    assert model._requests == []


def test_food_chat_agent_session_and_profile_context():
    with TestClient(
        create_app(settings(food_agent_mode="gemini", food_search_enabled=True))
    ) as client:
        model = FakeGemini()
        client.app.state.conversations.runner("food").agent.model = model
        client.put(
            "/api/profile",
            json={
                "country": "India",
                "allergies": ["peanuts", "milk"],
                "age_group": "child",
                "food_countries": ["India", "EU", "US"],
            },
        )
        info = next(a for a in client.get("/api/agents").json() if a["id"] == "food")
        assert info["enabled"] is True
        assert "google_search" in info["capabilities"]
        assert "web_fetch" in info["capabilities"]

        res = client.post("/api/agents/food/sessions")
        assert res.status_code == 201
        session_id = res.json()["id"]
        assert res.json()["title"] == "New review"

        reply = client.post(
            f"/api/agents/food/sessions/{session_id}/messages",
            json={
                "text": "Hi! Can you check the ingredients: wheat flour, sugar, E102, palm oil",
                "request_id": str(uuid4()),
            },
        )
        assert reply.status_code == 200
        messages = reply.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

        req = model._requests[-1]
        instruction = str(req.config.system_instruction)
        assert "peanuts" in instruction
        assert "child" in instruction


def test_food_has_independent_120_second_turn_timeout():
    service = ConversationService(settings(), InMemorySessionService())
    try:
        assert service.registration("food").timeout_seconds(service.settings) == 120
        custom = settings(food_timeout_seconds=145)
        assert service.registration("food").timeout_seconds(custom) == 145
        assert service.registration("stylist").timeout_seconds(custom) == 120
    finally:
        asyncio.run(service.close())


def test_accepted_turn_can_be_polled_and_replayed_without_duplicate_call(chat_client):
    client, _model = chat_client
    model = SlowGemini()
    client.app.state.conversations.runner("stylist").agent.model = model
    session_id = new_session(client)
    request_id = str(uuid4())
    url = f"/api/agents/stylist/sessions/{session_id}/turns"
    payload = {"text": "Mehendi outfit", "request_id": request_id}

    accepted = client.post(url, json=payload)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["request_id"] == request_id
    assert accepted.json()["status"] == "queued"
    assert accepted.json()["progress"] == {"stage": "queued", "label": "Waiting to start"}

    replay = client.post(url, json=payload)
    assert replay.status_code == 202
    assert replay.json()["request_id"] == request_id

    turn = wait_for_turn(client, "stylist", session_id, request_id)
    assert turn["status"] == "succeeded"
    assert turn["progress"]["stage"] == "complete"
    assert turn["error"] is None
    assert turn["retry"] is None
    assert len(model._requests) == 1

    conversation = client.get(f"/api/agents/stylist/sessions/{session_id}").json()
    assert [message["role"] for message in conversation["messages"]] == [
        "user",
        "assistant",
    ]
    assert "Private model reasoning" not in str(conversation) + str(turn)


class Researcher(BaseLlm):
    """Always wants one more lookup, like the live food agent on a broad question."""

    model: str = "gemini-test"
    _requests: list = PrivateAttr(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        self._requests.append(llm_request.model_copy(deep=True))
        config = llm_request.config.tool_config
        if config and config.function_calling_config.mode == types.FunctionCallingConfigMode.NONE:
            yield LlmResponse(
                content=types.Content(
                    role="model", parts=[types.Part(text="Lay's Classic: potato, oil, salt.")]
                )
            )
            return
        call = types.FunctionCall(
            name="lookup_ingredient_database",
            args={"ingredient_name": f"additive {len(self._requests)}"},
        )
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(function_call=call)])
        )


def test_food_answers_from_gathered_evidence_when_its_step_budget_runs_out():
    app_settings = settings(food_agent_mode="gemini", food_max_llm_calls=4)
    with TestClient(create_app(app_settings)) as client:
        model = Researcher()
        client.app.state.conversations.runner("food").agent.model = model
        session_id = client.post("/api/agents/food/sessions").json()["id"]

        response = client.post(
            f"/api/agents/food/sessions/{session_id}/messages",
            json={"text": "Ingredients of Lays chips in India", "request_id": str(uuid4())},
        )

        assert response.status_code == 200, response.text
        assert response.json()["messages"][-1]["text"] == "Lay's Classic: potato, oil, salt."
        assert len(model._requests) == 4
        *research, final = model._requests
        assert all(request.config.tool_config is None for request in research)
        assert "last step for this reply" in str(final.config.system_instruction)
        # The final call still sees every lookup result gathered so far.
        responses = [
            part.function_response
            for content in final.contents
            for part in content.parts or []
            if part.function_response
        ]
        assert len(responses) == 3


def test_accepted_food_failure_has_one_canonical_error_and_retry_metadata():
    with TestClient(create_app(settings(food_agent_mode="gemini"))) as client:
        model = SlowGemini()
        model._failure = RuntimeError("secret error details")
        client.app.state.conversations.runner("food").agent.model = model
        session_id = client.post("/api/agents/food/sessions").json()["id"]
        request_id = str(uuid4())
        url = f"/api/agents/food/sessions/{session_id}/turns"

        assert (
            client.post(
                url, json={"text": "Check this ingredient", "request_id": request_id}
            ).status_code
            == 202
        )
        turn = wait_for_turn(client, "food", session_id, request_id)
        assert turn["status"] == "failed"
        assert turn["error"]["code"] == "provider_failure"
        assert turn["error"]["message"].startswith("The food companion could not")
        assert len(turn["error"]["diagnostic_id"]) == 12
        assert turn["retry"] == {
            "allowed": True,
            "after_seconds": None,
            "use_new_request_id": True,
        }
        assert "secret" not in str(turn)

        saved = client.get(f"/api/agents/food/sessions/{session_id}").json()
        errors = [message for message in saved["messages"] if message["status"] == "error"]
        assert len(errors) == 1
        assert errors[0]["request_id"] == request_id
        assert errors[0]["error"] == turn["error"]
        assert errors[0]["retry"] == turn["retry"]

        replay = client.post(url, json={"text": "Check this ingredient", "request_id": request_id})
        assert replay.status_code == 202
        assert replay.json()["status"] == "failed"
        assert len(model._requests) == 1


def test_orphaned_accepted_turn_becomes_one_recoverable_failure():
    async def check():
        service = ConversationService(settings(), InMemorySessionService())
        session = await service.create("stylist", "user-a")
        request_id = uuid4()
        created_at = time.time()
        await service._record_progress(
            "stylist",
            "user-a",
            session.id,
            str(request_id),
            "running",
            "understanding",
            created_at,
        )

        first = await service.get_turn("stylist", "user-a", session.id, request_id)
        second = await service.get_turn("stylist", "user-a", session.id, request_id)
        assert first.status == second.status == "failed"
        assert first.error and first.error.code == "interrupted"
        conversation = await service.get("stylist", "user-a", session.id)
        assert len([message for message in conversation.messages if message.status == "error"]) == 1
        await service.close()

    asyncio.run(check())


@pytest.mark.parametrize(
    "failure,status",
    [
        (TimeoutError("internal details"), 504),
        (RuntimeError("secret error details"), 502),
        (
            ClientError(
                429, {"error": {"message": "private quota details", "status": "RESOURCE_EXHAUSTED"}}
            ),
            429,
        ),
    ],
)
def test_failure_saved_without_internal_details_and_recovery(chat_client, failure, status, caplog):
    client, model = chat_client
    model._failure = failure
    session_id = new_session(client)
    request_id = str(uuid4())
    response = send(client, session_id, "Mehendi outfit", request_id)
    assert response.status_code == status
    assert len(response.headers["X-Diagnostic-ID"]) == 12
    assert "details" not in response.text
    saved = client.get(f"/api/agents/stylist/sessions/{session_id}").json()
    assert saved["messages"][-1]["status"] == "error"
    assert saved["messages"][-1]["error"]["diagnostic_id"] == response.headers["X-Diagnostic-ID"]
    assert f"diagnostic_id={response.headers['X-Diagnostic-ID']}" in caplog.text
    assert f"request_id={request_id}" in caplog.text
    assert send(client, session_id, "Mehendi outfit", request_id).status_code == 200
    assert len(model._requests) == 1
    model._failure = None
    assert send(client, session_id, "Please continue").status_code == 200


def test_sqlite_history_survives_new_service(tmp_path):
    async def check():
        url = f"sqlite+aiosqlite:///{(tmp_path / 'sessions.db').as_posix()}"
        service = ConversationService(settings(), DatabaseSessionService(url))
        service.runner("stylist").agent.model = FakeGemini()
        session = await service.create("stylist", "user-a")
        await service.send(
            "stylist",
            "user-a",
            session.id,
            ChatRequest(text="Mehendi outfit", request_id=uuid4()),
            Profile(),
        )
        await service.close()
        fresh = ConversationService(settings(), DatabaseSessionService(url))
        try:
            saved = await fresh.get("stylist", "user-a", session.id)
            assert len(saved.messages) == 2
            assert saved.title == "Mehendi outfit"
            assert await fresh.list("stylist", "user-b") == []
        finally:
            await fresh.close()

    asyncio.run(check())


def test_quota_delay_is_returned_and_safe_message_saved(chat_client, caplog):
    client, model = chat_client
    model._failure = ClientError(
        429,
        {
            "error": {
                "message": "private-provider-payload",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "8.1s",
                    }
                ],
            }
        },
    )
    session_id = new_session(client)
    response = send(client, session_id, "Mehendi outfit")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "9"
    saved = client.get(f"/api/agents/stylist/sessions/{session_id}").json()
    assert saved["messages"][-1]["text"] == response.json()["detail"]
    assert "private-provider-payload" not in caplog.text + response.text + str(saved)
    assert "reason=quota_retry retry_after=9" in caplog.text


def test_turn_limit_and_concurrent_requests():
    async def check():
        service = ConversationService(
            settings(agent_max_conversation_turns=1), InMemorySessionService()
        )
        service.runner("stylist").agent.model = FakeGemini()
        session = await service.create("stylist", "user-a")
        service._active.add(("stylist", "user-a", session.id))
        with pytest.raises(HTTPException) as busy:
            await service.send(
                "stylist",
                "user-a",
                session.id,
                ChatRequest(text="first", request_id=uuid4()),
                Profile(),
            )
        assert busy.value.status_code == 409
        service._active.clear()
        await service.send(
            "stylist",
            "user-a",
            session.id,
            ChatRequest(text="first", request_id=uuid4()),
            Profile(),
        )
        with pytest.raises(HTTPException) as limit:
            await service.send(
                "stylist",
                "user-a",
                session.id,
                ChatRequest(text="second", request_id=uuid4()),
                Profile(),
            )
        assert limit.value.status_code == 409
        assert not service._active
        await service.close()

    asyncio.run(check())


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_delete_all_removes_only_the_users_chats_images_and_looks(chat_client):
    from app.schemas import LookBrief

    client, _ = chat_client
    app = client.app
    service = app.state.conversations
    looks = app.state.looks
    session_id = new_session(client)
    assert send(client, session_id, "Mehendi outfit").status_code == 200
    upload = client.post(
        f"/api/agents/stylist/sessions/{session_id}/attachments",
        files={"image": ("ref.png", PNG, "image/png")},
    )
    assert upload.status_code == 201, upload.text
    brief = LookBrief(occasion="Mehendi", total_budget_minor=600000)
    look = asyncio.run(looks.create_for_session("local-demo-user", session_id, brief))
    board = asyncio.run(looks.create("local-demo-user", look.model_copy(update={"id": "sample-board", "mode": "board"})))

    client.app.dependency_overrides[current_user] = lambda: "another-user"
    other_id = new_session(client)
    client.app.dependency_overrides.pop(current_user)

    response = client.delete("/api/agents/sessions")
    assert response.status_code == 200, response.text
    assert response.json() == {"conversations": 1, "looks": 1}
    assert client.get("/api/agents/stylist/sessions").json() == []
    assert client.get(f"/api/agents/stylist/sessions/{session_id}").status_code == 404
    assert asyncio.run(
        service.artifacts.list_artifact_keys(
            app_name="intentcart_stylist", user_id="local-demo-user", session_id=session_id
        )
    ) == []
    remaining = asyncio.run(looks.list_looks("local-demo-user"))
    assert [item.id for item in remaining] == [board.id]  # sample boards are not chats
    assert client.delete("/api/agents/sessions").json() == {"conversations": 0, "looks": 0}

    client.app.dependency_overrides[current_user] = lambda: "another-user"
    assert [s["id"] for s in client.get("/api/agents/stylist/sessions").json()] == [other_id]


def test_delete_all_cancels_a_running_turn(chat_client):
    client, _ = chat_client
    slow = SlowGemini()
    slow._delay = 5
    client.app.state.conversations.runner("stylist").agent.model = slow
    session_id = new_session(client)
    accepted = client.post(
        f"/api/agents/stylist/sessions/{session_id}/turns",
        json={"text": "Mehendi outfit", "request_id": str(uuid4())},
    )
    assert accepted.status_code == 202
    started = time.monotonic()
    assert client.delete("/api/agents/sessions").json()["conversations"] == 1
    assert time.monotonic() - started < 3
    assert client.get("/api/agents/stylist/sessions").json() == []


def test_deleted_sqlite_history_stays_deleted_after_restart(tmp_path):
    async def check():
        url = f"sqlite+aiosqlite:///{(tmp_path / 'sessions.db').as_posix()}"
        service = ConversationService(settings(), DatabaseSessionService(url))
        service.runner("stylist").agent.model = FakeGemini()
        mine = await service.create("stylist", "user-a")
        await service.send(
            "stylist", "user-a", mine.id, ChatRequest(text="Mehendi", request_id=uuid4()), Profile()
        )
        theirs = await service.create("stylist", "user-b")
        assert (await service.delete_all("user-a")).conversations == 1
        await service.close()
        fresh = ConversationService(settings(), DatabaseSessionService(url))
        try:
            assert await fresh.list("stylist", "user-a") == []
            assert [s.id for s in await fresh.list("stylist", "user-b")] == [theirs.id]
            with pytest.raises(HTTPException):
                await fresh.get("stylist", "user-a", mine.id)
        finally:
            await fresh.close()

    asyncio.run(check())
