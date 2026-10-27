"""ORM models: each class is one database table, each attribute one column."""

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Status(StrEnum):
    """Where an application is in the hiring funnel (stored as plain text)."""

    WISHLIST = "Wishlist"
    APPLIED = "Applied"
    OA = "OA"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECTED = "Rejected"


def utc_now() -> datetime:
    """Current time in UTC; used as the default for timestamp columns."""
    return datetime.now(UTC)


class Application(Base):
    """One job / placement application."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    ctc_lpa: Mapped[float | None]  # cost to company, in lakhs per annum
    status: Mapped[str] = mapped_column(String(20), default=Status.WISHLIST, index=True)
    applied_on: Mapped[date | None]
    next_step_date: Mapped[date | None] = mapped_column(index=True)  # OA / interview / deadline
    job_link: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    # One application has many history rows (one-to-many).
    # cascade="all, delete-orphan": deleting an application deletes its history too.
    history: Mapped[list["StatusHistory"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="StatusHistory.id",
    )


class StatusHistory(Base):
    """One row per status change, so we can show a timeline and compute the funnel."""

    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(20))  # None = just created
    to_status: Mapped[str] = mapped_column(String(20))
    changed_at: Mapped[datetime] = mapped_column(default=utc_now)

    application: Mapped[Application] = relationship(back_populates="history")
