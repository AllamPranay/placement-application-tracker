"""Pydantic schemas: the shape of JSON coming in (validated) and going out.

Models (models.py) describe database tables; schemas describe the API contract.
Keeping them separate means the API never leaks columns by accident.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Status

# SQLite does not store timezones, so timestamps come back "naive".
# We know we saved them in UTC, so we re-attach UTC before sending JSON
# (the browser then receives e.g. "2026-10-27T09:30:00Z" and shows local time).
UtcDateTime = Annotated[
    datetime, AfterValidator(lambda dt: dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt)
]

DATE_ORDER_ERROR = "next_step_date cannot be before applied_on"


def dates_in_order(applied_on: date | None, next_step_date: date | None) -> bool:
    """A next step (OA, interview...) cannot happen before you applied."""
    return applied_on is None or next_step_date is None or next_step_date >= applied_on


class ApplicationCreate(BaseModel):
    """Body of POST /api/applications. Only company and role are required."""

    # Strip spaces from strings and store enum values ("OA"), not enum objects.
    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)

    company: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    ctc_lpa: float | None = Field(default=None, ge=0)
    status: Status = Status.WISHLIST
    applied_on: date | None = None
    next_step_date: date | None = None
    job_link: str | None = Field(default=None, max_length=500, pattern=r"^https?://\S+$")
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def check_date_order(self) -> "ApplicationCreate":
        """Cross-field rule: runs after each field has been validated on its own."""
        if not dates_in_order(self.applied_on, self.next_step_date):
            raise ValueError(DATE_ORDER_ERROR)
        return self


class ApplicationUpdate(BaseModel):
    """Body of PUT /api/applications/{id}. Every field is optional: only the
    fields you send are changed (partial update)."""

    model_config = ConfigDict(str_strip_whitespace=True, use_enum_values=True)

    company: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    ctc_lpa: float | None = Field(default=None, ge=0)
    status: Status | None = None
    applied_on: date | None = None
    next_step_date: date | None = None
    job_link: str | None = Field(default=None, max_length=500, pattern=r"^https?://\S+$")
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("company", "role", "status")
    @classmethod
    def not_null(cls, value):
        """These columns are required, so an explicit null is rejected."""
        if value is None:
            raise ValueError("cannot be null")
        return value


class StatusUpdate(BaseModel):
    """Body of PATCH /api/applications/{id}/status."""

    model_config = ConfigDict(use_enum_values=True)

    status: Status


class ApplicationOut(BaseModel):
    """An application as returned by the API."""

    # from_attributes lets Pydantic read values straight from an ORM object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    company: str
    role: str
    location: str | None
    ctc_lpa: float | None
    status: Status
    applied_on: date | None
    next_step_date: date | None
    job_link: str | None
    notes: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class StatusHistoryOut(BaseModel):
    """One entry of an application's status timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: Status | None
    to_status: Status
    changed_at: UtcDateTime


class FunnelOut(BaseModel):
    """How many applications ever reached each stage, and stage-to-stage conversion %."""

    reached: dict[str, int]
    applied_to_oa_pct: float
    oa_to_interview_pct: float
    interview_to_offer_pct: float


class StatsOut(BaseModel):
    """Response of GET /api/stats."""

    total: int
    active: int
    by_status: dict[str, int]
    funnel: FunnelOut
    upcoming_7_days: int
    avg_offer_ctc_lpa: float | None
