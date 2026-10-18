# Conversational agents

`/clothes` is now **Shop a look**: a Gemini stylist that builds a complete look on a
live look board, with reference images, verified product discovery, small-business
labels and AI concept images. See [shop-a-look.md](shop-a-look.md) for that flow.
The original deterministic sample board remains at `/clothes/board`.

Agents run on **Google ADK 2.x**. ADK 2 logs node failures with tracebacks and
records `str(error)` on error events, so every runner is built through
`app/agents/privacy.py` (`adk_app`), which redacts both.

## Enable and run

Keep the existing backend `.env` and set:

For Vertex AI, follow [local ADC setup](vertex-ai.md) and use its provider settings
instead of the API key below. The agent mode and search settings apply to both providers.

```dotenv
AGENT_MODE=demo
STYLIST_AGENT_MODE=gemini
STYLIST_SEARCH_ENABLED=false
FOOD_AGENT_MODE=gemini
FOOD_TIMEOUT_SECONDS=120
GOOGLE_API_KEY=your-server-side-key
GEMINI_MODEL=gemini-flash-latest
AGENT_SESSION_BACKEND=sqlite
```

`STYLIST_AGENT_MODE` overrides the global mode for the chat agent only. Food and
the sample board can continue in demo mode. If the override is unset, the stylist
follows `AGENT_MODE`. There is no fake conversational response when it is disabled:
the UI shows that live chat is unavailable.

From `backend/`, run `uv sync --frozen --extra cloud`, then restart the API. From
`frontend/`, run `npm ci` and `npm run dev`. Use a model available to your API key.
Pin a concrete supported model ID before a release.
The latest alias is a development convenience, not a version guarantee.

Google Search is disabled by default. The stylist collects requirements and offers
outfit ideas and budget targets without browsing or claiming verified product
prices. The UI reads the agent's capabilities and hides the Google Search badge.
To enable search later, select a compatible model/project with grounding quota,
set `STYLIST_SEARCH_ENABLED=true` in `backend/.env`, and restart the backend.
The setting controls both the actual ADK tool list and the agent's instructions.

Try:

1. “I want an outfit for my sister's mehendi.”
2. Answer the stylist's budget and outfit-preference questions.
3. “My budget is INR 6000, shopping in India. A green kurta set for an outdoor daytime event. Suggest two outfit combinations.”
4. “Can you find something lighter and less embellished?”

The agent retains the earlier brief. When search is enabled, it can decide to use
Google Search and returns suggestions with the provider's grounding metadata. Search results
are evidence to inspect, not guaranteed price, inventory, or delivery data.

## Structure

```mermaid
flowchart TD
  UI[Shop a look chat] --> API[Authenticated agent routes]
  API --> Registry[Agent registry]
  Registry --> Service[Conversation service]
  Service --> Runner[Long-lived ADK Runner]
  Runner --> Stylist[Stylist LlmAgent]
  Stylist -. when enabled .-> Search[Google Search built-in tool]
  Runner <--> Sessions[ADK SessionService]
  Sessions --> SQLite[Local SQLite / test memory]
  Runner --> Public[Public reply + grounding projection]
  Public --> UI
```

| File | Responsibility |
| --- | --- |
| `backend/app/agents/base.py` | Immutable `AgentDefinition` and shared `LlmAgent` construction policy |
| `backend/app/agents/registry.py` | Agent factory, display name, enablement and allowed profile context |
| `backend/app/agents/stylist_agent.py` | Stylist definition, tools and style-only context |
| `backend/app/agents/prompts/stylist_conversation.md` | Actual clarification / planning / search instructions |
| `backend/app/agents/conversations.py` | Runner lifetime, sessions, turn limits, duplicate protection and errors |
| `backend/app/agents/grounding.py` | Public text, sources, citation-to-source mapping and search entry point |
| `backend/app/routers/agents.py` | Agent-neutral HTTP API; identity always comes from authentication |
| `frontend/src/pages/ShopLook.tsx` | Conversation creation, follow-up messages, recent chats and composer |
| `frontend/src/components/AgentMessage.tsx` | Markdown and grounded response display |

ADK already supplies `BaseAgent` and `LlmAgent`. We use composition instead of a
second base-agent inheritance hierarchy. The shared factory also constructs the
existing schema-constrained Food steps. The stylist has normal conversation
history and optional native Google Search, with no output schema forcing the reply into
product JSON. Its role is to orchestrate the conversation, not to simulate a
separate planner or execute purchases.

To add Food chat or another vertical, create its prompt/factory and register an
`AgentRegistration` with a suitable profile-context projection. The generic session
routes do not change. Each agent receives a separate ADK app namespace, preventing
accidental cross-agent history sharing. Only style preferences and country are
supplied to the stylist; saved allergies and dietary data stay out of its context.
For future specialist delegation, use ADK `sub_agents` for handoffs or `AgentTool`
when a coordinator should regain control. Keep native search/tool-combination
constraints and grounding propagation in mind when adding tools.

## Sessions, failures and boundaries

- A runner and agent are shared, while all user data lives in user-scoped ADK
  sessions. A new conversation gets a server-generated ID.
- Local SQLite at `backend/.data/agent_sessions.db` preserves chat across API
  restarts. It is ignored by Git and Docker. Firestore profiles/looks and ADK
  conversation events are different stores. `AGENT_SESSION_BACKEND=memory` is
  useful for tests and deliberately loses chat on restart.
- Authenticated users cannot read or send to another user's session. Demo auth
  still uses one shared local identity and must not be exposed as private service.
- A whole turn is protected against overlapping requests within one process.
  `request_id` is a client UUID and idempotency key. Replaying an accepted,
  running or terminal request returns saved state without another Gemini call.
  A retry or follow-up uses a new UUID.
- New clients should use the accepted-turn API below. It persists
  `queued -> running -> succeeded/failed`, with a safe progress vocabulary:
  `queued`, `understanding`, `planning`, `searching`, `researching`, `preparing`,
  `complete` and `failed`. These are application-owned labels, never model
  thoughts, prompts, tool arguments or raw tool results.
- Timeouts and provider failures preserve history and append exactly one canonical
  public error message. Terminal turn state and that message carry the same error
  code and retry advice. Food has `FOOD_TIMEOUT_SECONDS=120` by default; Shop a
  Look has `STYLIST_TIMEOUT_SECONDS=120`. Errors name the relevant assistant
  instead of always referring to a stylist.
- Each turn has a model-call budget (`FOOD_MAX_LLM_CALLS=10`,
  `STYLIST_MAX_LLM_CALLS=12`). The last allowed call runs with function calling
  disabled, so a turn that spends its budget on research still ends with an
  answer built from the evidence it gathered rather than an error.
- The blocking compatibility route retains its historical HTTP error response.
  Its clients must render either that response or the refreshed transcript, not
  both. The server never returns raw SDK errors, secrets or internal thoughts.
- Raw tool payloads and thought parts are excluded from the public transcript.
  Google Search's source URLs, support mappings and HTML/CSS search entry point
  are preserved. Markdown cannot execute raw HTML; the provider's search snippet
  is rendered in a sandboxed iframe with scripts and parent-origin access blocked.
- This implementation uses one API worker. Accepted turns run as in-process tasks;
  SQLite preserves lifecycle events, not the running coroutine. After a process
  restart, polling a formerly queued/running turn records one `interrupted` failure
  so the UI does not spin forever and the user can follow up. Graceful shutdown
  also records interruption for active accepted turns. Before multi-instance
  deployment, add a durable queue, shared session service and distributed
  per-session lease. Database event locks alone do not serialize a model call.
- There is no token/SSE streaming. Polling is the supported fallback and progress
  advances only at safe application/agent event boundaries. Built-in Google Search
  may not emit a distinct tool event, so the server does not invent granular steps.

## Endpoints

All routes below require the current user identity and start with `/api`:

| Method | Route | Result |
| --- | --- | --- |
| GET | `/agents` | Registered agents, enablement and current capabilities |
| POST | `/agents/stylist/sessions` | New empty conversation |
| GET | `/agents/stylist/sessions` | Current user's recent conversations |
| GET | `/agents/stylist/sessions/{id}` | Public conversation history |
| POST | `/agents/{agent}/sessions/{id}/turns` | Preferred: accept `{ "text": "...", "request_id": "UUID", "attachments": [] }`; return `202` plus `TurnStatus` immediately |
| GET | `/agents/{agent}/sessions/{id}/turns/{request_id}` | Poll authenticated, user-scoped status for that idempotency key |
| POST | `/agents/{agent}/sessions/{id}/messages` | Compatibility: block until completion and return updated history; failures retain their HTTP status |

`TurnStatus` has this stable shape (timestamps are Unix seconds):

```json
{
  "request_id": "82ee1fb7-828c-4e85-bef0-795c59db3d80",
  "agent_id": "food",
  "session_id": "...",
  "status": "running",
  "progress": {"stage": "researching", "label": "Checking trusted food sources"},
  "created_at": 1792310400.0,
  "updated_at": 1792310401.2,
  "error": null,
  "retry": null
}
```

On failure, `error` is `{ "code": "timeout", "message": "..." }` and
`retry` is `{ "allowed": true, "after_seconds": null,
"use_new_request_id": true }`. Quota delays populate `after_seconds`; permanent
configuration or zero-quota failures set `allowed` to `false`.

Frontend integration:

1. Generate one UUID and `POST .../turns` once. Keep the draft until the `202`.
2. Show `progress.label` and poll `GET .../turns/{request_id}` about once per second.
   Reuse the UUID when retrying an uncertain network request; it cannot duplicate
   the Gemini call.
3. At `succeeded` or `failed`, stop polling and fetch the conversation once. Render
   its assistant/error message as the canonical bubble. Do not create another
   error bubble from the status response.
4. If `retry.allowed`, Retry/Continue sends a new turn with a new UUID, observing
   `after_seconds` when supplied.

## Verification

`uv run pytest -q` exercises the actual ADK runner with a deterministic test LLM:
history, native search configuration, style-only context, grounding projection,
ownership, duplicate requests, failures, turn limits and SQLite restart persistence.
No normal test needs an API key or makes network calls.

An explicit live test is available separately:

```powershell
uv run python -m scripts.smoke_stylist
```

It makes two real Gemini turns and respects `STYLIST_SEARCH_ENABLED`. With search
enabled, it also checks that the second turn returns grounded source links. It uses
only a synthetic brief and an in-memory session. This can incur normal API costs.
It does not read saved profiles or modify real conversations.

## Troubleshooting Gemini 429 responses

To check just the key and a minimal text request, independently of ADK, sessions
and Google Search, run from `backend/`:

```powershell
uv run python scripts/check_google_key.py
# Authentication check only, without generating text:
uv run python scripts/check_google_key.py --auth-only
```

The script reads `GOOGLE_API_KEY` and `GEMINI_MODEL` from `backend/.env`. A process
environment variable overrides the file, just as in the backend. It reports model
listing and generation separately: listing can succeed while generation fails
with 429. The full check makes one small generation request and can incur normal
API costs. Exit code `0` means the requested checks passed; `1` means a failure.
Keys and raw provider errors are never printed.

Creating or reading a session does not call Gemini. A successful `201` for session
creation followed by `429` when sending a message means the provider rejected the
model request; starting another conversation does not replenish provider quota.

1. Open [AI Studio rate limits](https://aistudio.google.com/usage?tab=rate-limit)
   for the project associated with `GOOGLE_API_KEY`. Check the model selected by
   `GEMINI_MODEL` and the project's billing tier. Limits apply per project, so
   making another key within the same project does not add quota.
2. If the enforced limit is zero, review model availability and billing setup, or
   explicitly select a model with available quota that supports Google Search.
   Do not assume every model or `latest` alias has free-tier access.
3. If a daily allowance is exhausted, wait for its reset or review the project's
   quota. Gemini's requests-per-day limits reset at midnight Pacific time. For
   temporary throttling, wait at least the returned delay before a new follow-up.
4. After changing `backend/.env`, restart the backend. From `backend/`, run
   `uv run python -m scripts.diagnose_gemini` to make one small synthetic request
   using the configured search setting. Add `--search` to explicitly test Google
   Search before enabling it in the app. This uses the configured key/model and can incur
   normal API costs; it does not retry, read chat history, or change settings.

The API and saved transcript distinguish reported zero/daily quotas and temporary
retry delays. When supplied, a usable delay is also returned as `Retry-After`.
Server logs include a fixed reason code and delay, never the raw provider payload.
Some 429 responses contain no quota breakdown: `quota_unspecified` means the
project's AI Studio quota page is needed to distinguish quota from capacity.
No automatic model switching or additional application retry loop is used.

See [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) for
project scope, reset times and tier rules.

## ADK references used

- [ADK Google Search grounding](https://adk.dev/grounding/google_search_grounding/): native `google_search` on an `LlmAgent`.
- [ADK sessions](https://adk.dev/sessions/session/): runner/session separation, persistence and database concurrency.
- [ADK tool limitations](https://adk.dev/tools/limitations/): composition patterns when adding specialist tools.
- [ADK workflows](https://adk.dev/workflows/): later multi-agent orchestration options.
- [Google Search entry point](https://firebase.google.com/docs/reference/js/ai.searchentrypoint): preserving provider-supplied search presentation.
