# IntentCart

IntentCart is a conversational shopping assistant with two named specialists: **Nia, the Food Guide**, and **Mira, the Personal Stylist**. Nia combines deterministic ingredient/profile checks, source-backed regulation and IARC data, optional gap research, citation verification, and grounded follow-ups. Mira builds a complete look on a live board with reference images, a confirmable checklist, market-informed budget planning, verified product discovery, lock/swap controls, and AI concept images.

The architecture document is used as product context. Your request takes precedence: **Google ADK replaces LangGraph**, and all model steps use configurable Gemini models. No cloud resources were created or deployed.

## Start locally

Prerequisites: Node.js 22.12+ and Python 3.12 or 3.13. The recommended Python package manager is [uv](https://docs.astral.sh/uv/). Run the following in two terminals from this directory.

Backend (PowerShell):

```powershell
cd backend
Copy-Item .env.example .env
uv sync --frozen --extra cloud
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend (PowerShell):

```powershell
cd frontend
Copy-Item .env.example .env
npm ci
npm run dev
```

`npm ci` installs from the committed lockfile. On macOS/Linux use `cp` instead of `Copy-Item`; the remaining commands are the same. Without uv, create a virtual environment and run `pip install -e ".[cloud]"` inside `backend/` (the uv route is the reproducible one).

- App: <http://127.0.0.1:5173>
- API docs and request examples: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/api/health>

No API keys are needed for the sample look board or structured Food label demo. In this mode, the live Nia and Mira chat composers show as offline. Demo auth uses **one shared local user**; profile/board data stays in process memory and resets when the API restarts. Chat history uses a separate local SQLite store by default.

Accepted chat turns run as background tasks in the API process and expose safe, pollable progress stages to the UI. Run **one API worker** locally. Do not expose demo auth as a private multi-user service.

For live **Mira / Shop a look**, add `STYLIST_AGENT_MODE=gemini` and configure [Vertex AI with local ADC](docs/vertex-ai.md) or a server-side `GOOGLE_API_KEY` in `backend/.env`, keeping `AGENT_MODE=demo` if Food should remain a demo. Set `STYLIST_SEARCH_ENABLED=true` for live product discovery, restart the API, and open Clothes.

For live **Nia / Food Guide**, add `FOOD_AGENT_MODE=gemini`. `FOOD_SEARCH_ENABLED=true` enables grounded source checks. Nia and Mira each default to a 120-second whole-turn timeout through `FOOD_TIMEOUT_SECONDS` and `STYLIST_TIMEOUT_SECONDS`.

A minimal local configuration for both live specialists is:

```dotenv
AGENT_MODE=demo
FOOD_AGENT_MODE=gemini
STYLIST_AGENT_MODE=gemini
FOOD_SEARCH_ENABLED=true
STYLIST_SEARCH_ENABLED=true
GOOGLE_API_KEY=your-server-side-key
```

Use the Vertex AI settings from `docs/vertex-ai.md` instead of `GOOGLE_API_KEY` when running with ADC. Never place the Gemini key in `frontend/.env` or any `VITE_*` variable.

See [Shop a Look](docs/shop-a-look.md) and [conversational agents](docs/agents.md) for architecture, configuration, progress lifecycle details, and live smoke tests.

Keep `STYLIST_SEARCH_ENABLED=false` for conversational styling without browsing. To enable Google Search later, choose a compatible model/project with available grounding quota, set `STYLIST_SEARCH_ENABLED=true`, and restart the backend.

## Sign-in (static accounts)

`AUTH_MODE=static` enables two fixed accounts, John and Jane. The landing page stays public. Chatting with Nia or Mira, the sample board and My profile require sign-in, and a signed-out visitor is redirected to `/login` and then returned to the page they asked for.

```powershell
cd backend
uv run python scripts/hash_password.py john jane
```

The script prompts for each password (12+ characters, not echoed) and prints `AUTH_MODE`, `STATIC_USERS` and a random `AUTH_SECRET_KEY`. Put these lines in `backend/.env`, or in your deployment's secret environment, and restart the API. No frontend setting is needed.

- Passwords are checked only by the API, against salted scrypt hashes. Neither the passwords nor the hashes reach the browser bundle.
- A successful sign-in sets an HMAC-signed, expiring cookie (`HttpOnly`, `SameSite=Strict`, path `/api`, and `Secure` when `APP_ENV=production`). Page scripts cannot read it, and editing it invalidates it.
- Every API route still checks the cookie on the server, so calling the API directly without signing in returns `401`.
- After 5 failed attempts in 15 minutes, an account is locked for the rest of that window.
- Changing a user's password hash, or rotating `AUTH_SECRET_KEY`, signs that user (or everyone) out.
- Static auth needs the frontend and API on the same origin. That is the default for the Vite proxy and the single-container deployment.

**Delete all chats:** My profile → *Delete all chats* permanently removes the signed-in user's Nia and Mira conversations, their attached and generated images, and Mira's linked look boards (`DELETE /api/agents/sessions`). The rows are deleted from the session database rather than hidden. The `.data` directory is excluded from the Docker image, so a redeploy cannot restore them.

## Try the flows

**Nia / Food Guide:** open Food and start a chat with a question or pasted ingredient label. While Nia works, the conversation shows safe stages such as understanding, checking trusted sources, and preparing the answer. The structured scanner remains available for text, barcode, and photo input. Save `milk, peanut` as allergies in My profile to validate personalized warnings. Set `FOOD_AGENT_MODE=gemini` for live conversation and `AGENT_MODE=gemini` for structured gap research. See [food agent setup and evidence limits](docs/food-agent.md).

**Mira / Shop a look:** attach a reference photo and ask Mira to recreate the look within a total budget. Review the proposed checklist and item-level price ranges, then mark pieces as owned, remove them, or add another piece. Mira surveys verified prices, replans the whole basket, and searches within the resulting caps. Lock products, request cheaper options, or use **Update look** for changes such as more formal, a different palette, or popular stores only. Removing an item redistributes the remaining budget automatically. Chats and boards can be resumed from the left session rail.

**Sample board (`/clothes/board`):** enter an occasion and budget → edit and confirm the checklist → select sample products → swap, own or remove pieces → assemble the look. This remains separate from agent chat for now.

Prices are integer paise in the API; ₹6,000 is `600000`. The backend recomputes allocations, preserves every paise, and validates selections. Verified store-page prices replace conservative category ranges as discovery completes. When every open item has a verified option, the plan records whether a complete basket fits the total budget. The client never supplies a trusted price.

## What is built, and what is a placeholder?

| Area | Current behavior |
| --- | --- |
| React / Vite / TypeScript / Tailwind | Named Nia/Mira entry points; responsive session rail; look-board/chat workspace; persistent composer; safe progress and single-error rendering; React Query and Zustand |
| FastAPI | Typed REST contracts, OpenAPI, user-scoped records, confirmation boundaries, accepted background turns with idempotent request IDs, pollable progress, and same-origin static serving |
| Google ADK + Gemini | Nia food conversation and Mira styling conversation; food extraction, research, structured reporting and QA; shared agent factory, sessions, tool progress and agent-specific limits |
| Food text | Editable confirmation, alias/E-number normalization, deterministic allergen/diet matches, scoped age notes, structured report and scan history |
| Food barcode | ZXing camera component; opt-in Open Food Facts adapter, with text fallback |
| Food photo | Validated upload route and transcription prompt; requires Gemini credentials, then user confirmation |
| Food evidence | Reviewed regulation/IARC seeds, country matrix, hard-allowlisted fetch, Google Search via AgentTool, citation checks and expiring Firestore/memory evidence cache. Missing evidence remains unverified |
| Clothes | Checklist confirmation; market-informed complete-basket planning; automatic redistribution; 14 illustrative seed products; lock/swap/owned/remove; whole-look refinement and final totals |
| Clothes discovery | ADK 2 workflow per checklist item: Google Search nominates pages; prices/images/stock are verified from product pages; category ranges and reserved options inform the plan; ranking considers fit, preferred platforms, and a popular-retailer-first policy. Verified small businesses remain distinctly labelled. Reference-image analysis/editing, Pinterest inspiration, Maps boutiques |
| Auth / memory | Working local adapter; static John/Jane accounts with signed HttpOnly cookies; Firebase token verification, Google sign-in, and Firestore adapters included but not cloud-tested |
| PWA / container | App-shell PWA configuration, manifest and icon; multi-stage Dockerfile for one Cloud Run service |
| Deferred | SSE transport (the UI currently polls), a distributed production turn queue/shared lease for multiple API workers, cloud image history, checkout, price tracking, furniture and accessories |

The demo matching dictionary is incomplete and can produce both missed and false matches. It is for exercising the flow, not determining medical suitability. The app never uses an absence of findings as a safety verdict.

## Repository map

```text
intentcart/
  backend/
    app/
      main.py                 # App factory, routing, static frontend serving
      config.py               # Environment settings and mode validation
      auth.py                 # Demo identity / static sign-in cookies / Firebase tokens
      schemas.py              # API contracts and persisted records
      routers/                # profile, food, clothes
      agents/
        llm.py                # ADK LlmAgent factory and model selection
        conversations.py      # Nia/Mira sessions, accepted turns and safe progress
        conversation_schemas.py # Conversation, turn, error and retry contracts
        food_agent.py         # Extract / research / report / follow-up agents
        food_pipeline.py      # Deterministic checks, research, verification and caching
        stylist_agent.py      # Mira coordinator and styling agent
        runtime.py            # Shared ADK Runner + temporary sessions
        schemas.py            # Model output contracts
        prompts/              # Agent instructions; unfinished look-board steps retain TODO_PROMPT
      clothes/                # Look service, discovery workflow, sellers and page verification
      tools/                  # Label matching, regulations, OFF and budget planning
      memory/store.py         # Store protocol, memory and Firestore adapters
      data/                   # Allergen examples, empty rules, sample catalog
    tests/                    # Flow, ownership, confirmation and budget checks
    pyproject.toml, uv.lock
  frontend/
    src/pages/                # Home, FoodCheck, ShopLook, LookBoard, Profile
    src/components/           # Chat workspace, session rail, progress, scanners and look cards
    src/lib/                  # API, accepted-turn polling, agent metadata, Firebase and types
    src/store/                # Look board state
    package.json, package-lock.json
  docs/designs/               # Reviewable desktop/mobile UI concepts
  docs/architecture.md
  docs/implementation-todos.md
  Dockerfile
  firestore.rules
```

## Connect the real services

1. Food and `stylist_conversation.md` prompts are implemented. For the remaining structured look-board steps, replace each relevant `TODO_PROMPT` in `backend/app/agents/prompts/`; unchanged markers return HTTP 501 before a model call.
2. Configure [Vertex AI with ADC](docs/vertex-ai.md), or set `GOOGLE_API_KEY` for the Gemini Developer API. Set `GEMINI_MODEL` and `GEMINI_LITE_MODEL`, then enable both specialists with `AGENT_MODE=gemini` or enable them independently with `FOOD_AGENT_MODE=gemini` and/or `STYLIST_AGENT_MODE=gemini`. Credentials stay on the server. Select explicit model IDs available to your project and provider; the default latest aliases are scaffolding conveniences and are not pinned model versions. Run a small smoke call after configuring prompts.
3. For barcode lookup, set `ENABLE_OPEN_FOOD_FACTS=true` and a real contact in `OPEN_FOOD_FACTS_USER_AGENT`. Review [Open Food Facts API requirements](https://openfoodfacts.github.io/openfoodfacts-server/api/) and its data licensing before publishing.
4. For Firebase, enable Google sign-in and Firestore, set `GOOGLE_CLOUD_PROJECT`, `AUTH_MODE=firebase`, `STORE_BACKEND=firestore`, and use Application Default Credentials. Configure the matching `VITE_FIREBASE_*` values and `VITE_AUTH_MODE=firebase` in `frontend/.env`. Add the frontend origin to Firebase's authorized domains. The backend uses the Admin SDK; direct client database access is denied by `firestore.rules`.
5. Populate and review the reference data, then implement the remaining adapters listed in [implementation-todos.md](docs/implementation-todos.md). Gemini explanations are not a replacement for deterministic checks or reviewed evidence.

The ADK integration follows the official [Python quickstart](https://adk.dev/get-started/python/) and [LlmAgent structured output](https://adk.dev/agents/llm-agents/) APIs. Dependencies are pinned by `uv.lock`; the app uses ADK 2.x (graph/dynamic workflows for product discovery).

## Verify

```powershell
cd backend
uv run pytest -q
cd ../frontend
npm run build
```

Tests run without external API calls. They cover confirmed food analysis, edited ingredients, record ownership, exact and market-informed budget allocation, removal-driven replanning, popular-retailer ranking, lock/swap transitions, accepted-turn idempotency, safe progress, agent-specific timeouts, and single canonical failures.

Before a release, validate these behaviors with real credentials and devices:

1. Start both agents and confirm Nia and Mira transition from **Offline** to **Ready**.
2. Send a message and confirm the composer stays visible while progress advances and exactly one reply or error appears.
3. Ask Mira for a shirt, trousers, and footwear under ₹4,000; review the proposed ranges and complete-basket result.
4. Remove one item and confirm the remaining caps are redistributed. Use **Update look** and confirm selected pieces remain selected.
5. With `STYLIST_SEARCH_ENABLED=true`, confirm preferred/popular retailers rank ahead of unknown stores when suitable verified products are available.
6. Test barcode/photo capture on target mobile hardware over HTTPS if those inputs will be released.

Cloud credentials, live Gemini/Search behavior, real retailer availability, and camera hardware require this separate integration testing.

## Container / Cloud Run preparation

From `intentcart/`:

```powershell
docker build -t intentcart .
docker run --rm -p 8080:8080 intentcart
```

Then open <http://localhost:8080>. FastAPI serves both `/api` and the frontend, including direct navigation to `/food` and `/clothes`. The container honors Cloud Run's `PORT` environment variable.

For an actual multi-user deployment, build with the Firebase web configuration as Docker build arguments (same names as `frontend/.env.example`), use a Cloud Run service account with scoped Firestore access, inject the Gemini key using Secret Manager, and set `APP_ENV=production`, `AUTH_MODE=firebase`, and `STORE_BACKEND=firestore`. Production mode refuses demo identity or in-memory storage. Complete transaction/concurrency handling and the remaining integration checks before relying on it in production. Firebase build arguments are public web configuration; never pass Gemini credentials as build arguments.

The PWA caches only the app shell. API reports and profiles are not cached by the service worker; backend access is still required. Mobile installability and camera permissions need testing on target devices over HTTPS.
