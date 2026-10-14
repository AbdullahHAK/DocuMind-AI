"""FastAPI application entry point.

    uvicorn app.main:app --reload

In production the built React frontend (frontend/dist) is served from the
same origin, so the browser never needs CORS and there's one URL to deploy.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.services import Services, build_services

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(services: Services | None = None, *, warm_up: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = services or build_services(get_settings())
        svc.startup()
        if warm_up:
            svc.retriever.embedder.warm_up()  # load models now, not on the first user's request
        app.state.services = svc
        yield

    app = FastAPI(title="Am I Covered?", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()
