# IntentCart scaffold

A shopping assistant with two flows: **Food label review** and **Shop a look**. Food reviews combine deterministic ingredient/profile checks, source-backed regulation and IARC data, optional gap research, citation verification, and grounded follow-ups. The stylist builds a complete look on a live board: reference images, a confirmable checklist, verified product discovery (with small-business labels), lock/swap per item, and AI concept images.

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

No API keys are needed for the sample board and Food demo. Demo auth uses **one shared local user**; profile/board data stays in process memory and resets when the API restarts. Chat history uses a separate local SQLite store by default. Run one API worker locally. Do not expose demo auth as a private multi-user service.

For live **Shop a look**, add `STYLIST_AGENT_MODE=gemini` and configure [Vertex AI with local ADC](docs/vertex-ai.md) or a server-side `GOOGLE_API_KEY` in `backend/.env`, keeping `AGENT_MODE=demo` if Food should remain a demo. Restart the API and open Clothes. Set `STYLIST_SEARCH_ENABLED=true` for live product discovery. See [Shop a Look](docs/shop-a-look.md) and [conversational agents](docs/agents.md) for architecture, configuration, and the live smoke tests.

Keep `STYLIST_SEARCH_ENABLED=false` for conversational styling without browsing. To enable Google Search later, choose a compatible model/project with available grounding quota, set `STYLIST_SEARCH_ENABLED=true`, and restart the backend.

## Try the flows

**Food:** save `milk, peanut` as allergies in My profile → Food → Try a sample label → Review ingredients → edit and confirm the ingredient, contains, and may-contain fields → review purposes, IARC context and the country matrix. Recent labels can be reopened. Set `AGENT_MODE=gemini` for gap research and evidence-grounded follow-ups. See [food agent setup and evidence limits](docs/food-agent.md).

**Shop a look:** attach a reference photo and say “Help me recreate this Mehendi look, but with more affordable accessories” → give a budget → review the checklist on the board (own / remove / add) → confirm → products appear per item → lock pieces or ask for cheaper/matching alternatives → finish the look. Chats and their boards can be resumed from the sidebar.

**Sample board (`/clothes/board`):** enter an occasion and budget → edit and confirm the checklist → select sample products → swap, own or remove pieces → assemble the look. This remains separate from agent chat for now.

Prices are integer paise in the API; ₹6,000 is `600000`. The backend recomputes allocations and validates selections. The client never supplies a trusted price.

## What is built, and what is a placeholder?

| Area | Scaffold behavior |
| --- | --- |
| React / Vite / TypeScript / Tailwind | Responsive Home, Food, Clothes, Profile; loading/error states; React Query and Zustand |
| FastAPI | Typed REST contracts, OpenAPI, user-scoped records, confirmation boundaries, same-origin static serving |
| Google ADK + Gemini | Conversational stylist; food extraction, research, structured reporting and QA; shared agent factory, sessions and limits |
| Food text | Editable confirmation, alias/E-number normalization, deterministic allergen/diet matches, scoped age notes, structured report and scan history |
| Food barcode | ZXing camera component; opt-in Open Food Facts adapter, with text fallback |
| Food photo | Validated upload route and transcription prompt; requires Gemini credentials, then user confirmation |
| Food evidence | Reviewed regulation/IARC seeds, country matrix, hard-allowlisted fetch, Google Search via AgentTool, citation checks and expiring Firestore/memory evidence cache. Missing evidence remains unverified |
| Clothes | Checklist confirmation; deterministic allocation; 14 illustrative seed products; lock/swap/owned/remove; final totals |
| Clothes discovery | ADK 2 workflow per checklist item: Google Search nominates pages, prices/images/stock are read from each page's structured data, a ranking agent scores fit against locked pieces; independent sellers are labelled and favoured. Reference-image analysis/editing, Pinterest inspiration, Maps boutiques |
| Auth / memory | Working local adapter; Firebase token verification, Google sign-in, and Firestore adapters included but not cloud-tested |
| PWA / container | App-shell PWA configuration, manifest and icon; multi-stage Dockerfile for one Cloud Run service |
| Deferred | SSE progress, shared production session storage, cloud image history, checkout, price tracking, furniture and accessories |

The demo matching dictionary is incomplete and can produce both missed and false matches. It is for exercising the flow, not determining medical suitability. The app never uses an absence of findings as a safety verdict.

## Repository map

```text
intentcart/
  backend/
    app/
      main.py                 # App factory, routing, static frontend serving
      config.py               # Environment settings and mode validation
      auth.py                 # Demo identity / Firebase token verification
      schemas.py              # API contracts and persisted records
      routers/                # profile, food, clothes
      agents/
        llm.py                # ADK LlmAgent factory and model selection
        food_agent.py         # Extract / research / report / follow-up agents
        food_pipeline.py      # Deterministic checks, research, verification and caching
        stylist_agent.py      # Brief / final-note agents
        runtime.py            # Shared ADK Runner + temporary sessions
        schemas.py            # Model output contracts
        prompts/              # Agent instructions; unfinished look-board steps retain TODO_PROMPT
      tools/                  # Label matching, regulations, OFF, products, budget
      memory/store.py         # Store protocol, memory and Firestore adapters
      data/                   # Allergen examples, empty rules, sample catalog
    tests/                    # Flow, ownership, confirmation and budget checks
    pyproject.toml, uv.lock
  frontend/
    src/pages/                # Home, FoodCheck, LookBoard, Profile
    src/components/           # Scanner, editors, cards, summary, follow-up panel
    src/lib/                  # API, Firebase, types
    src/store/                # Look board state
    package.json, package-lock.json
  docs/architecture.md
  docs/implementation-todos.md
  Dockerfile
  firestore.rules
```

## Connect the real services

1. Food and `stylist_conversation.md` prompts are implemented. For the remaining structured look-board steps, replace each relevant `TODO_PROMPT` in `backend/app/agents/prompts/`; unchanged markers return HTTP 501 before a model call.
2. Configure [Vertex AI with ADC](docs/vertex-ai.md), or set `GOOGLE_API_KEY` for the Gemini Developer API. Set `GEMINI_MODEL`, `GEMINI_LITE_MODEL`, and `AGENT_MODE=gemini` in `backend/.env`. Credentials stay on the server. Select explicit model IDs available to your project and provider; the default latest aliases are scaffolding conveniences and are not pinned model versions. Run a small smoke call after configuring prompts.
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

Tests run without external API calls. They cover confirmed food analysis, edited ingredients, record ownership, exact budget allocation, affordable candidates, lock/swap transitions, and unfinished-integration responses. Cloud credentials, live Gemini calls and camera hardware require separate integration testing.

## Container / Cloud Run preparation

From `intentcart/`:

```powershell
docker build -t intentcart .
docker run --rm -p 8080:8080 intentcart
```

Then open <http://localhost:8080>. FastAPI serves both `/api` and the frontend, including direct navigation to `/food` and `/clothes`. The container honors Cloud Run's `PORT` environment variable.

For an actual multi-user deployment, build with the Firebase web configuration as Docker build arguments (same names as `frontend/.env.example`), use a Cloud Run service account with scoped Firestore access, inject the Gemini key using Secret Manager, and set `APP_ENV=production`, `AUTH_MODE=firebase`, and `STORE_BACKEND=firestore`. Production mode refuses demo identity or in-memory storage. Complete transaction/concurrency handling and the remaining integration checks before relying on it in production. Firebase build arguments are public web configuration; never pass Gemini credentials as build arguments.

The PWA caches only the app shell. API reports and profiles are not cached by the service worker; backend access is still required. Mobile installability and camera permissions need testing on target devices over HTTPS.
