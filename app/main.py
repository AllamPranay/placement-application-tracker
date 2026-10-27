"""Application entry point: creates the FastAPI app, the tables, and wires everything up.

Run with:  uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import applications, stats

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


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
app.include_router(stats.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness check used by Docker and uptime monitors."""
    return {"status": "ok"}


# The frontend: index.html at "/", CSS/JS under "/static/...".
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page frontend."""
    return FileResponse(STATIC_DIR / "index.html")
