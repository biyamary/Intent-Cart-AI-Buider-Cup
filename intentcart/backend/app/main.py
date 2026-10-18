from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.conversations import (
    ConversationService,
    create_artifact_service,
    create_session_service,
)
from app.agents.food_pipeline import FoodPipeline
from app.agents.google_client import configure_adk_environment
from app.agents.runtime import AgentRuntime
from app.clothes.discovery import Discovery
from app.clothes.service import LookService
from app.clothes.studio import Studio
from app.clothes.tools import ShopServices
from app.config import Settings, get_settings
from app.memory.store import FirestoreStore, MemoryStore
from app.routers import agents, clothes, food, profile


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        if settings.auth_mode == "firebase":
            import firebase_admin

            try:
                firebase_admin.get_app()
            except ValueError:
                firebase_admin.initialize_app(options={"projectId": settings.google_cloud_project})
        if "gemini" in (settings.agent_mode, settings.stylist_mode, settings.food_mode):
            configure_adk_environment(settings)
        app.state.conversations = ConversationService(
            settings,
            create_session_service(settings),
            create_artifact_service(settings),
            ShopServices(settings, app.state.looks, app.state.discovery, app.state.studio),
        )
        try:
            yield
        finally:
            await app.state.discovery.close()
            await app.state.conversations.close()

    app = FastAPI(title="IntentCart API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = (
        FirestoreStore(settings.google_cloud_project)
        if settings.store_backend == "firestore"
        else MemoryStore()
    )
    app.state.agents = AgentRuntime(settings)
    app.state.looks = LookService(app.state.store)
    app.state.discovery = Discovery(settings, app.state.looks)
    app.state.studio = Studio(settings)
    app.state.food_pipeline = FoodPipeline(settings, app.state.store, app.state.agents)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/api/health", tags=["system"])
    async def health():
        return {
            "status": "ok",
            "agent_mode": settings.agent_mode,
            "stylist_agent_mode": settings.stylist_mode,
            "food_agent_mode": settings.food_mode,
            "auth_mode": settings.auth_mode,
            "store": settings.store_backend,
        }

    for router in (profile.router, food.router, clothes.router, agents.router):
        app.include_router(router, prefix="/api")

    dist = settings.frontend_dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "API route not found.")
        target = (dist / path).resolve()
        if not target.is_relative_to(dist):
            raise HTTPException(404, "File not found.")
        if target.is_file():
            return FileResponse(target)
        if "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(404, "Asset not found.")
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        raise HTTPException(404, "Frontend is not built. Run Vite on port 5173 or npm run build.")

    return app


app = create_app()
