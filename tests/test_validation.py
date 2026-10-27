"""Invalid input must be rejected with 422 Unprocessable Entity and a clear message."""

import pytest


def error_messages(response) -> str:
    """Join all error messages of a 422 response into one string for easy asserts."""
    detail = response.json()["detail"]
    if isinstance(detail, str):
        return detail
    return " | ".join(f"{e['loc'][-1]}: {e['msg']}" for e in detail)


@pytest.mark.parametrize(
    ("body", "expected_text"),
    [
        ({"role": "SDE"}, "company"),  # company missing
        ({"company": "   ", "role": "SDE"}, "company"),  # blank after stripping spaces
        ({"company": "TCS"}, "role"),  # role missing
        ({"company": "TCS", "role": "SDE", "status": "Ghosted"}, "status"),
        ({"company": "TCS", "role": "SDE", "ctc_lpa": -1}, "greater than or equal to 0"),
        ({"company": "TCS", "role": "SDE", "applied_on": "not-a-date"}, "applied_on"),
        ({"company": "TCS", "role": "SDE", "job_link": "careers.tcs.com"}, "job_link"),
    ],
)
def test_create_rejects_invalid_fields(client, body, expected_text):
    response = client.post("/api/applications", json=body)
    assert response.status_code == 422
    assert expected_text in error_messages(response)


def test_create_rejects_next_step_before_applied_on(client):
    body = {
        "company": "Infosys",
        "role": "SP",
        "applied_on": "2026-10-10",
        "next_step_date": "2026-10-01",
    }
    response = client.post("/api/applications", json=body)
    assert response.status_code == 422
    assert "next_step_date cannot be before applied_on" in error_messages(response)


def test_update_checks_dates_against_stored_value(client, make_application):
    created = make_application(applied_on="2026-10-10")
    response = client.put(
        f"/api/applications/{created['id']}", json={"next_step_date": "2026-10-01"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "next_step_date cannot be before applied_on"


def test_update_rejects_null_for_required_field(client, make_application):
    created = make_application()
    response = client.put(f"/api/applications/{created['id']}", json={"company": None})
    assert response.status_code == 422
    assert "cannot be null" in error_messages(response)


def test_status_endpoint_rejects_unknown_status(client, make_application):
    created = make_application()
    response = client.patch(f"/api/applications/{created['id']}/status", json={"status": "Done"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "params", [{"status": "Hired"}, {"sort": "salary"}, {"q": "x" * 101}]
)
def test_list_rejects_invalid_query_parameters(client, params):
    assert client.get("/api/applications", params=params).status_code == 422
