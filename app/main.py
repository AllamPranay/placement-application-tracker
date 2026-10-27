"""Application entry point: creates the FastAPI app, the tables, and wires everything up.

Run with:  uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routers import applications


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Runs once at startup: create any missing tables (no-op if they exist)."""
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Placement Application Tracker",
    description="Track job / placement applications through the hiring funnel.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(applications.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness check used by Docker and uptime monitors."""
    return {"status": "ok"}

