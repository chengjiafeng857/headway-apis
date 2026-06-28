from fastapi import FastAPI

from app.core.config import settings
from app.core.database import Base, engine
from app import models  # noqa: F401
from app.routers import (
    appointments,
    auth,
    notifications,
    provider_self,
    providers,
    watchers,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Headway Care API",
        version="0.1.0",
        description="Therapy provider search, appointment scheduling, and reopened-slot alerts.",
    )

    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)

    app.include_router(auth.router)
    # provider_self must be registered before the public providers router so that
    # "/providers/me" matches the self-service routes instead of being parsed as
    # "/providers/{provider_id}" (which would 422 on the non-int "me").
    app.include_router(provider_self.router)
    app.include_router(providers.router)
    app.include_router(appointments.router)
    app.include_router(watchers.router)
    app.include_router(notifications.router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
