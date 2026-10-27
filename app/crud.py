"""CRUD layer: every database query lives here, so routers stay small.

CRUD = Create, Read, Update, Delete. Functions take a Session and return ORM objects.
"""

from datetime import date, timedelta
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Application, Status, StatusHistory
from app.schemas import ApplicationCreate

SortOption = Literal["newest", "next_step_date", "applied_on", "company"]


def record_status_change(application: Application, new_status: str) -> bool:
    """Set a new status and append a history row. Returns False if nothing changed."""
    if application.status == new_status:
        return False
    application.history.append(StatusHistory(from_status=application.status, to_status=new_status))
    application.status = new_status
    return True


def create_application(db: Session, data: ApplicationCreate) -> Application:
    """Insert an application plus its first history row (None -> initial status)."""
    application = Application(**data.model_dump())
    application.history.append(StatusHistory(from_status=None, to_status=application.status))
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def get_application(db: Session, application_id: int) -> Application | None:
    """Fetch one application by primary key (None if it does not exist)."""
    return db.get(Application, application_id)


def list_applications(
    db: Session, status: str | None = None, q: str | None = None, sort: SortOption = "newest"
) -> list[Application]:
    """List applications with optional status filter, text search and sort order."""
    stmt = select(Application)
    if status:
        stmt = stmt.where(Application.status == status)
    if q:
        # icontains -> LOWER(column) LIKE '%' || LOWER(:q) || '%'  (q is a bound parameter)
        stmt = stmt.where(
            Application.company.icontains(q, autoescape=True)
            | Application.role.icontains(q, autoescape=True)
        )
    order_by = {
        "next_step_date": [Application.next_step_date.asc().nulls_last()],  # soonest first
        "applied_on": [Application.applied_on.desc().nulls_last()],  # most recent first
        "company": [func.lower(Application.company)],  # A to Z, ignoring case
        "newest": [Application.created_at.desc()],
    }[sort]
    stmt = stmt.order_by(*order_by, Application.id.desc())  # id breaks ties
    return list(db.scalars(stmt))


def update_application(db: Session, application: Application, changes: dict) -> Application:
    """Apply only the given fields. A status change goes through the history helper."""
    new_status = changes.pop("status", None)
    for field, value in changes.items():
        setattr(application, field, value)
    if new_status is not None:
        record_status_change(application, new_status)
    db.commit()
    db.refresh(application)
    return application


def change_status(db: Session, application: Application, new_status: str) -> Application:
    """Change only the status (used by PATCH /status)."""
    if record_status_change(application, new_status):
        db.commit()
        db.refresh(application)
    return application


def delete_application(db: Session, application: Application) -> None:
    """Delete an application; its history rows are deleted by the cascade."""
    db.delete(application)
    db.commit()


def get_history(db: Session, application_id: int) -> list[StatusHistory]:
    """Status timeline of one application, oldest first."""
    stmt = (
        select(StatusHistory)
        .where(StatusHistory.application_id == application_id)
        .order_by(StatusHistory.changed_at, StatusHistory.id)
    )
    return list(db.scalars(stmt))


def upcoming_applications(db: Session, days: int, today: date | None = None) -> list[Application]:
    """Applications whose next step falls between today and today + days (inclusive).
    Rejected applications are skipped: they have no real next step."""
    today = today or date.today()
    stmt = (
        select(Application)
        .where(Application.next_step_date.between(today, today + timedelta(days=days)))
        .where(Application.status != Status.REJECTED)
        .order_by(Application.next_step_date, Application.company)
    )
    return list(db.scalars(stmt))


def all_applications_for_export(db: Session) -> list[Application]:
    """Every application, oldest id first (for the CSV export)."""
    return list(db.scalars(select(Application).order_by(Application.id)))


# ---------------------------------------------------------------------------
# Stats: all numbers below are computed by the database with SQL aggregation.
# ---------------------------------------------------------------------------

# Pipeline order. "Reached Interview" also means it got past Applied and OA,
# even if the OA step was skipped. Wishlist and Rejected are not funnel stages.
STAGE_RANK = {Status.APPLIED: 1, Status.OA: 2, Status.INTERVIEW: 3, Status.OFFER: 4}
ACTIVE_STATUSES = [Status.APPLIED, Status.OA, Status.INTERVIEW]


def count_by_status(db: Session) -> dict[str, int]:
    """SELECT status, COUNT(id) FROM applications GROUP BY status."""
    stmt = select(Application.status, func.count(Application.id)).group_by(Application.status)
    counts = {status.value: 0 for status in Status}  # statuses with no rows show as 0
    counts.update({status: count for status, count in db.execute(stmt)})
    return counts


def funnel_reached(db: Session) -> dict[str, int]:
    """How many applications ever reached each stage.

    Step 1 (subquery): for each application, the highest stage it ever had,
    using status_history (it also holds the current status, because a history
    row is written on create and on every change).
    Step 2: count applications whose best stage is at least Applied / OA / ...
    """
    stage_rank = case(STAGE_RANK, value=StatusHistory.to_status, else_=0)
    best = (
        select(StatusHistory.application_id, func.max(stage_rank).label("best_stage"))
        .group_by(StatusHistory.application_id)
        .subquery()
    )

    def reached(rank: int):
        return func.coalesce(func.sum(case((best.c.best_stage >= rank, 1), else_=0)), 0)

    stmt = select(
        reached(1).label("Applied"),
        reached(2).label("OA"),
        reached(3).label("Interview"),
        reached(4).label("Offer"),
    )
    return dict(db.execute(stmt).one()._mapping)


def count_upcoming(db: Session, days: int = 7, today: date | None = None) -> int:
    """SELECT COUNT(id) ... WHERE next_step_date BETWEEN today AND today + days."""
    today = today or date.today()
    stmt = (
        select(func.count(Application.id))
        .where(Application.next_step_date.between(today, today + timedelta(days=days)))
        .where(Application.status != Status.REJECTED)
    )
    return db.scalar(stmt)


def average_offer_ctc(db: Session) -> float | None:
    """SELECT AVG(ctc_lpa) FROM applications WHERE status = 'Offer' (NULLs ignored)."""
    stmt = select(func.avg(Application.ctc_lpa)).where(Application.status == Status.OFFER)
    average = db.scalar(stmt)
    return round(average, 2) if average is not None else None
