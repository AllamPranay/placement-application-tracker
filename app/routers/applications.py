"""REST endpoints for applications, their status history, upcoming steps and CSV export."""

import csv
import io
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.models import Application, Status
from app.schemas import (
    DATE_ORDER_ERROR,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    StatusHistoryOut,
    StatusUpdate,
    dates_in_order,
)

router = APIRouter(prefix="/api", tags=["applications"])

CSV_COLUMNS = [
    "id", "company", "role", "location", "ctc_lpa", "status", "applied_on",
    "next_step_date", "job_link", "notes", "created_at", "updated_at",
]


def get_or_404(db: Session, application_id: int) -> Application:
    """Load an application or stop the request with 404 Not Found."""
    application = crud.get_application(db, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found")
    return application


@router.post("/applications", response_model=ApplicationOut, status_code=201)  # 201 Created
def create_application(data: ApplicationCreate, db: Session = Depends(get_db)):
    """Create an application. FastAPI has already validated `data` (or returned 422)."""
    return crud.create_application(db, data)


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    status: Status | None = None,
    q: str | None = Query(default=None, max_length=100, description="Search company or role"),
    sort: crud.SortOption = "newest",
    db: Session = Depends(get_db),
):
    """List applications, e.g. /api/applications?status=OA&q=tcs&sort=company"""
    return crud.list_applications(db, status=status, q=q, sort=sort)


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def read_application(application_id: int, db: Session = Depends(get_db)):
    """Get one application."""
    return get_or_404(db, application_id)


@router.put("/applications/{application_id}", response_model=ApplicationOut)
def update_application(application_id: int, data: ApplicationUpdate, db: Session = Depends(get_db)):
    """Partial update: only the fields present in the JSON body are changed."""
    application = get_or_404(db, application_id)
    changes = data.model_dump(exclude_unset=True)  # fields the client actually sent
    # Check the date rule on the *merged* result (new value, else the stored one).
    applied_on = changes.get("applied_on", application.applied_on)
    next_step_date = changes.get("next_step_date", application.next_step_date)
    if not dates_in_order(applied_on, next_step_date):
        raise HTTPException(status_code=422, detail=DATE_ORDER_ERROR)
    return crud.update_application(db, application, changes)


@router.delete("/applications/{application_id}", status_code=204)  # 204 No Content
def delete_application(application_id: int, db: Session = Depends(get_db)):
    """Delete an application (and, through the cascade, its history)."""
    crud.delete_application(db, get_or_404(db, application_id))
    return Response(status_code=204)


@router.patch("/applications/{application_id}/status", response_model=ApplicationOut)
def change_status(application_id: int, data: StatusUpdate, db: Session = Depends(get_db)):
    """Move an application to a new status and record the change in status_history."""
    return crud.change_status(db, get_or_404(db, application_id), data.status)


@router.get("/applications/{application_id}/history", response_model=list[StatusHistoryOut])
def read_history(application_id: int, db: Session = Depends(get_db)):
    """Status timeline of one application, oldest first."""
    get_or_404(db, application_id)
    return crud.get_history(db, application_id)


@router.get("/upcoming", response_model=list[ApplicationOut])
def upcoming(days: int = Query(default=7, ge=0, le=365), db: Session = Depends(get_db)):
    """Applications with a next step in the next `days` days, soonest first."""
    return crud.upcoming_applications(db, days)


def csv_line(values: list) -> str:
    """Format one row as CSV text (csv.writer takes care of commas and quotes)."""
    buffer = io.StringIO()
    csv.writer(buffer).writerow(values)
    return buffer.getvalue()


def csv_lines(applications: list[Application]) -> Iterator[str]:
    """Generator: yield the file one line at a time, so the response is sent in
    chunks instead of building one big string in memory first."""
    yield csv_line(CSV_COLUMNS)
    for application in applications:
        yield csv_line([getattr(application, column) for column in CSV_COLUMNS])


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)):
    """Download every application as a CSV file."""
    applications = crud.all_applications_for_export(db)
    headers = {"Content-Disposition": 'attachment; filename="applications.csv"'}
    return StreamingResponse(csv_lines(applications), media_type="text/csv", headers=headers)
