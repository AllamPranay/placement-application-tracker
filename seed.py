"""Fill the database with SAMPLE data so the app has something to show.

    python seed.py           # only seeds an empty database
    python seed.py --reset   # deletes ALL applications first, then seeds

Every row below is made-up sample data (company names are used only to look
realistic; the roles, CTCs and dates are invented). Dates are relative to today,
so the dashboard always has upcoming OAs and interviews.
"""

import sys
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, func, select

from app.database import Base, SessionLocal, engine
from app.models import Application, StatusHistory

# (company, role, location, ctc_lpa, applied N days ago, next step in N days, journey, notes)
# journey = every status the application went through, in order; the last one is current.
SAMPLE_DATA = [
    ("Accenture", "Associate Software Engineer", "Bengaluru", 4.5, 20, 2,
     ["Applied", "OA"], "Cognitive + coding assessment"),
    ("TCS", "Digital – Software Engineer", "Hyderabad", 7.0, 30, 5,
     ["Applied", "OA", "Interview"], "TR + MR + HR in one day"),
    ("Infosys", "Specialist Programmer", "Pune", 9.5, 6, None,
     ["Applied"], None),
    ("Cognizant", "GenC Next", "Chennai", 6.75, 40, None,
     ["Applied", "OA", "Rejected"], "Cleared aptitude, coding round was tough"),
    ("Deloitte", "Analyst – Data & Analytics", "Hyderabad", 7.6, 25, 1,
     ["Applied", "OA", "Interview"], "Revise SQL window functions"),
    ("Zoho", "Member Technical Staff", "Chennai", 8.4, 45, 12,
     ["Applied", "OA", "Interview", "Offer"], "Offer letter received; accept by deadline"),
    ("Freshworks", "Software Engineer I", "Chennai", 12.0, 14, 3,
     ["Applied", "OA"], "HackerRank OA, 90 minutes"),
    ("Swiggy", "Data Analyst", "Bengaluru", 14.0, 9, None,
     ["Applied"], "Referral from a senior"),
    ("Wipro", "Project Engineer (Turbo)", "Bengaluru", 6.5, 50, None,
     ["Applied", "Interview", "Offer"], "Direct interview, no OA"),
    ("Capgemini", "Analyst", "Mumbai", 4.25, 35, None,
     ["Applied", "Rejected"], None),
    ("PhonePe", "Business Analyst", "Bengaluru", 15.0, None, 6,
     ["Wishlist"], "Application deadline"),
    ("Flipkart", "SDE-1", "Bengaluru", 18.0, None, 9,
     ["Wishlist"], "Waiting for campus drive"),
    ("HCLTech", "Graduate Engineer Trainee", "Noida", 4.0, 3, 10,
     ["Applied"], None),
    ("Tiger Analytics", "Data Analyst", "Chennai", 8.0, 18, 0,
     ["Applied", "OA", "Interview"], "Case-study round today"),
    ("Razorpay", "Data Engineer", "Bengaluru", 16.0, 28, None,
     ["Applied", "OA", "Interview", "Rejected"], "Ask for feedback"),
]

# A few sample rows link to the company's public careers page.
JOB_LINKS = {
    "Accenture": "https://www.accenture.com/in-en/careers",
    "Zoho": "https://www.zoho.com/careers/",
    "Freshworks": "https://www.freshworks.com/company/careers/",
}


def build_application(row: tuple, today: date) -> Application:
    """Turn one SAMPLE_DATA row into an Application with a back-dated status history."""
    company, role, location, ctc, applied_ago, next_in, journey, notes = row
    applied_on = today - timedelta(days=applied_ago) if applied_ago is not None else None
    start_day = applied_on or today - timedelta(days=4)  # wishlist items were added recently
    start = datetime.combine(start_day, time(10, 0), tzinfo=UTC)

    application = Application(
        company=company,
        role=role,
        location=location,
        ctc_lpa=ctc,
        status=journey[-1],
        applied_on=applied_on,
        next_step_date=today + timedelta(days=next_in) if next_in is not None else None,
        job_link=JOB_LINKS.get(company),
        notes=notes,
        created_at=start,
        updated_at=start,
    )
    # One history row per step, spaced a few days apart (never in the future).
    previous = None
    for step, status in enumerate(journey):
        changed_at = min(start + timedelta(days=4 * step), datetime.now(UTC))
        application.history.append(
            StatusHistory(from_status=previous, to_status=status, changed_at=changed_at)
        )
        application.updated_at = changed_at
        previous = status
    return application


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        existing = db.scalar(select(func.count(Application.id)))
        if existing and "--reset" not in sys.argv:
            print(f"Database already has {existing} applications. "
                  "Run 'python seed.py --reset' to delete them and load the sample data.")
            return
        db.execute(delete(StatusHistory))
        db.execute(delete(Application))
        today = date.today()
        db.add_all(build_application(row, today) for row in SAMPLE_DATA)
        db.commit()
    print(f"Seeded {len(SAMPLE_DATA)} SAMPLE applications (made-up data for demo purposes).")


if __name__ == "__main__":
    main()
