import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.core.config import settings
from app.core.database import Base, engine
from app import models  # noqa: F401
from app.realtime.routes import router as realtime_router
from app.realtime.stream_listener import consume_redis_stream
from app.routers import (
    appointments,
    auth,
    follows,
    notifications,
    patient_self,
    provider_self,
    providers,
    watchers,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    stop_event = asyncio.Event()
    stream_task: asyncio.Task | None = None
    if settings.websocket_redis_consumer_enabled:
        stream_task = asyncio.create_task(consume_redis_stream(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        if stream_task is not None:
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Headway Care API",
        version="0.1.0",
        description="Therapy provider search, appointment scheduling, and reopened-slot alerts.",
        lifespan=lifespan,
    )

    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)

    app.include_router(auth.router)
    app.include_router(patient_self.router)
    # provider_self must be registered before the public providers router so that
    # "/providers/me" matches the self-service routes instead of being parsed as
    # "/providers/{provider_id}" (which would 422 on the non-int "me").
    app.include_router(provider_self.router)
    app.include_router(providers.router)
    app.include_router(appointments.router)
    app.include_router(follows.router)
    app.include_router(watchers.router)
    app.include_router(notifications.router)
    app.include_router(realtime_router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
