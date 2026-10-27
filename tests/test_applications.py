"""CRUD, filtering, searching, sorting and status-history tests."""

from sqlalchemy import func, select

from app.models import StatusHistory
from tests.conftest import days_from_today


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Placement Application Tracker" in response.text


def test_create_application_returns_201_and_saved_fields(client):
    body = {
        "company": "  Zoho  ",
        "role": "Member Technical Staff",
        "location": "Chennai",
        "ctc_lpa": 8.4,
        "status": "Applied",
        "applied_on": "2026-10-01",
        "next_step_date": "2026-10-20",
        "job_link": "https://careers.zohocorp.com",
        "notes": "Referral from senior",
    }
    response = client.post("/api/applications", json=body)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] > 0
    assert data["company"] == "Zoho"  # surrounding spaces are stripped
    assert data["status"] == "Applied"
    assert data["ctc_lpa"] == 8.4
    assert data["created_at"].endswith("Z")  # timestamps are sent as UTC


def test_create_defaults_to_wishlist(make_application):
    assert make_application()["status"] == "Wishlist"


def test_get_application_by_id(client, make_application):
    created = make_application(company="TCS")
    response = client.get(f"/api/applications/{created['id']}")
    assert response.status_code == 200
    assert response.json()["company"] == "TCS"


def test_get_missing_application_returns_404(client):
    response = client.get("/api/applications/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Application 999 not found"


def test_list_returns_newest_first(client, make_application):
    make_application(company="First")
    make_application(company="Second")
    names = [a["company"] for a in client.get("/api/applications").json()]
    assert names == ["Second", "First"]


def test_filter_by_status(client, make_application):
    make_application(company="A", status="Applied")
    make_application(company="B", status="OA")
    make_application(company="C", status="OA")
    data = client.get("/api/applications", params={"status": "OA"}).json()
    assert sorted(a["company"] for a in data) == ["B", "C"]


def test_search_is_case_insensitive_on_company_and_role(client, make_application):
    make_application(company="Freshworks", role="Software Engineer")
    make_application(company="Swiggy", role="Data Analyst")
    make_application(company="Infosys", role="Systems Engineer")
    by_company = client.get("/api/applications", params={"q": "FRESH"}).json()
    by_role = client.get("/api/applications", params={"q": "analyst"}).json()
    assert [a["company"] for a in by_company] == ["Freshworks"]
    assert [a["company"] for a in by_role] == ["Swiggy"]


def test_search_treats_percent_sign_literally(client, make_application):
    make_application(company="Acme")
    assert client.get("/api/applications", params={"q": "%"}).json() == []


def test_sort_by_company_ignores_case(client, make_application):
    for name in ["zoho", "Accenture", "Infosys"]:
        make_application(company=name)
    data = client.get("/api/applications", params={"sort": "company"}).json()
    assert [a["company"] for a in data] == ["Accenture", "Infosys", "zoho"]


def test_sort_by_next_step_date_puts_empty_dates_last(client, make_application):
    make_application(company="NoDate")
    make_application(company="Later", next_step_date=days_from_today(9))
    make_application(company="Sooner", next_step_date=days_from_today(2))
    data = client.get("/api/applications", params={"sort": "next_step_date"}).json()
    assert [a["company"] for a in data] == ["Sooner", "Later", "NoDate"]


def test_sort_by_applied_on_most_recent_first(client, make_application):
    make_application(company="Old", applied_on="2026-08-01")
    make_application(company="New", applied_on="2026-10-01")
    data = client.get("/api/applications", params={"sort": "applied_on"}).json()
    assert [a["company"] for a in data] == ["New", "Old"]


def test_update_changes_only_sent_fields(client, make_application):
    created = make_application(company="Deloitte", location="Hyderabad", ctc_lpa=7.6)
    response = client.put(f"/api/applications/{created['id']}", json={"ctc_lpa": 8.0})
    assert response.status_code == 200
    data = response.json()
    assert data["ctc_lpa"] == 8.0
    assert data["location"] == "Hyderabad"  # untouched


def test_update_missing_application_returns_404(client):
    assert client.put("/api/applications/42", json={"role": "X"}).status_code == 404


def test_delete_returns_204_then_404(client, make_application):
    created = make_application()
    assert client.delete(f"/api/applications/{created['id']}").status_code == 204
    assert client.get(f"/api/applications/{created['id']}").status_code == 404
    assert client.delete(f"/api/applications/{created['id']}").status_code == 404


def test_create_writes_first_history_row(client, make_application):
    created = make_application(status="Applied")
    history = client.get(f"/api/applications/{created['id']}/history").json()
    assert len(history) == 1
    assert history[0]["from_status"] is None
    assert history[0]["to_status"] == "Applied"


def test_status_change_writes_history(client, make_application):
    created = make_application(status="Applied")
    url = f"/api/applications/{created['id']}"
    assert client.patch(f"{url}/status", json={"status": "OA"}).json()["status"] == "OA"
    client.patch(f"{url}/status", json={"status": "Interview"})
    history = client.get(f"{url}/history").json()
    assert [(h["from_status"], h["to_status"]) for h in history] == [
        (None, "Applied"),
        ("Applied", "OA"),
        ("OA", "Interview"),
    ]


def test_same_status_does_not_add_history(client, make_application):
    created = make_application(status="OA")
    client.patch(f"/api/applications/{created['id']}/status", json={"status": "OA"})
    assert len(client.get(f"/api/applications/{created['id']}/history").json()) == 1


def test_status_change_through_put_also_writes_history(client, make_application):
    created = make_application(status="Applied")
    client.put(f"/api/applications/{created['id']}", json={"status": "Rejected"})
    history = client.get(f"/api/applications/{created['id']}/history").json()
    assert history[-1]["from_status"] == "Applied"
    assert history[-1]["to_status"] == "Rejected"


def test_status_and_history_of_missing_application_return_404(client):
    assert client.patch("/api/applications/7/status", json={"status": "OA"}).status_code == 404
    assert client.get("/api/applications/7/history").status_code == 404


def test_delete_cascades_to_status_history(client, db_session, make_application):
    created = make_application(status="Applied")
    client.patch(f"/api/applications/{created['id']}/status", json={"status": "OA"})
    count_history = select(func.count()).select_from(StatusHistory)
    assert db_session.scalar(count_history) == 2
    client.delete(f"/api/applications/{created['id']}")
    assert db_session.scalar(count_history) == 0
