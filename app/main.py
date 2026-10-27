"""Application entry point: creates the FastAPI app.

Run with:  uvicorn app.main:app --reload
"""

from fastapi import FastAPI


app = FastAPI(
    title="Placement Application Tracker",
    description="Track job / placement applications through the hiring funnel.",
    version="1.0.0",
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness check used by Docker and uptime monitors."""
    return {"status": "ok"}

