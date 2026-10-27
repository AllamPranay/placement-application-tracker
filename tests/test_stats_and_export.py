"""Stats / funnel math on a known fixture, the upcoming window, and CSV export."""

import csv
import io

import pytest

from tests.conftest import days_from_today


@pytest.fixture
def funnel_fixture(client, make_application):
    """Six applications with known journeys through the funnel.

    Wishlist                      -> never applied
    Applied                       -> reached Applied
    Applied -> OA -> Rejected     -> reached Applied, OA
    Applied -> OA -> Interview    -> reached Applied, OA, Interview
    Applied -> Interview -> Offer -> reached all four (OA skipped, still counts)
    Applied -> OA -> Interview -> Offer
    """
    journeys = [
        ("Wishlist", [], None),
        ("Applied", [], None),
        ("Applied", ["OA", "Rejected"], None),
        ("Applied", ["OA", "Interview"], None),
        ("Applied", ["Interview", "Offer"], 12.0),
        ("Applied", ["OA", "Interview", "Offer"], 8.0),
    ]
    for index, (start, moves, ctc) in enumerate(journeys):
        created = make_application(company=f"Company {index}", status=start, ctc_lpa=ctc)
        for new_status in moves:
            client.patch(f"/api/applications/{created['id']}/status", json={"status": new_status})


def test_stats_on_empty_database(client):
    stats = client.get("/api/stats").json()
    assert stats["total"] == 0
    assert stats["active"] == 0
    assert set(stats["by_status"].values()) == {0}
    assert stats["funnel"]["reached"] == {"Applied": 0, "OA": 0, "Interview": 0, "Offer": 0}
    assert stats["funnel"]["applied_to_oa_pct"] == 0.0
    assert stats["avg_offer_ctc_lpa"] is None


def test_stats_counts_per_status(client, funnel_fixture):
    stats = client.get("/api/stats").json()
    assert stats["total"] == 6
    assert stats["by_status"] == {
        "Wishlist": 1, "Applied": 1, "OA": 0, "Interview": 1, "Offer": 2, "Rejected": 1,
    }
    assert stats["active"] == 2  # Applied + OA + Interview


def test_funnel_reached_and_conversion(client, funnel_fixture):
    funnel = client.get("/api/stats").json()["funnel"]
    assert funnel["reached"] == {"Applied": 5, "OA": 4, "Interview": 3, "Offer": 2}
    assert funnel["applied_to_oa_pct"] == 80.0  # 4 / 5
    assert funnel["oa_to_interview_pct"] == 75.0  # 3 / 4
    assert funnel["interview_to_offer_pct"] == 66.7  # 2 / 3, rounded to 1 decimal


def test_average_offer_ctc(client, funnel_fixture):
    assert client.get("/api/stats").json()["avg_offer_ctc_lpa"] == 10.0  # (12 + 8) / 2


def test_upcoming_window_is_inclusive_and_sorted(client, make_application):
    make_application(company="Past", next_step_date=days_from_today(-1))
    make_application(company="Today", next_step_date=days_from_today(0))
    make_application(company="InSeven", next_step_date=days_from_today(7))
    make_application(company="InThree", next_step_date=days_from_today(3))
    make_application(company="TooFar", next_step_date=days_from_today(8))
    make_application(company="NoDate")
    data = client.get("/api/upcoming", params={"days": 7}).json()
    assert [a["company"] for a in data] == ["Today", "InThree", "InSeven"]
    assert client.get("/api/stats").json()["upcoming_7_days"] == 3


def test_upcoming_skips_rejected_and_respects_days(client, make_application):
    make_application(company="Rejected", status="Rejected", next_step_date=days_from_today(1))
    make_application(company="Soon", next_step_date=days_from_today(2))
    assert [a["company"] for a in client.get("/api/upcoming").json()] == ["Soon"]
    assert client.get("/api/upcoming", params={"days": 1}).json() == []


def test_upcoming_rejects_negative_days(client):
    assert client.get("/api/upcoming", params={"days": -1}).status_code == 422


def test_export_csv_download(client, make_application):
    make_application(company="Swiggy", role="Data Analyst", ctc_lpa=14, notes='Said "call me", later')
    make_application(company="Zoho", role="MTS")
    response = client.get("/api/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [r["company"] for r in rows] == ["Swiggy", "Zoho"]
    assert rows[0]["ctc_lpa"] == "14.0"
    assert rows[0]["notes"] == 'Said "call me", later'  # commas and quotes survive


def test_export_csv_with_no_rows_has_only_header(client):
    lines = client.get("/api/export.csv").text.strip().splitlines()
    assert lines == [
        "id,company,role,location,ctc_lpa,status,applied_on,next_step_date,"
        "job_link,notes,created_at,updated_at"
    ]
