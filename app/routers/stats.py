"""Dashboard statistics: counts per status, funnel conversion, upcoming steps, offer CTC."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.schemas import FunnelOut, StatsOut

router = APIRouter(prefix="/api", tags=["stats"])


def percent(part: int, whole: int) -> float:
    """part / whole as a percentage with one decimal; 0.0 when whole is 0."""
    return round(100 * part / whole, 1) if whole else 0.0


@router.get("/stats", response_model=StatsOut)
def read_stats(db: Session = Depends(get_db)):
    """Every number is computed in SQL (COUNT, GROUP BY, SUM(CASE), AVG)."""
    by_status = crud.count_by_status(db)
    reached = crud.funnel_reached(db)
    funnel = FunnelOut(
        reached=reached,
        applied_to_oa_pct=percent(reached["OA"], reached["Applied"]),
        oa_to_interview_pct=percent(reached["Interview"], reached["OA"]),
        interview_to_offer_pct=percent(reached["Offer"], reached["Interview"]),
    )
    return StatsOut(
        total=sum(by_status.values()),
        active=sum(by_status[s] for s in crud.ACTIVE_STATUSES),
        by_status=by_status,
        funnel=funnel,
        upcoming_7_days=crud.count_upcoming(db, days=7),
        avg_offer_ctc_lpa=crud.average_offer_ctc(db),
    )
