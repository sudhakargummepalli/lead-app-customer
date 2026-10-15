import os
import tempfile

import pytest

os.environ["LEADS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PRIYA = {
    "name": "Priya Raman",
    "phone": "+91 98765 43210",
    "email": "Priya@Example.com",
    "address": "14 Lake View Road, Hyderabad 500034",
    "status": "new",
    "source": "Website",
}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        for lead in c.get("/api/leads").json():
            c.delete(f"/api/leads/{lead['id']}")
        yield c


def test_create_and_get(client):
    r = client.post("/api/leads", json=PRIYA)
    assert r.status_code == 201
    lead = r.json()
    assert lead["email"] == "priya@example.com"
    assert client.get(f"/api/leads/{lead['id']}").json()["name"] == "Priya Raman"


def test_requires_contact(client):
    r = client.post("/api/leads", json={"name": "No Contact"})
    assert r.status_code == 422


def test_rejects_bad_email_and_phone(client):
    assert client.post("/api/leads", json={**PRIYA, "email": "not-an-email"}).status_code == 422
    assert client.post("/api/leads", json={**PRIYA, "phone": "123"}).status_code == 422


def test_duplicate_is_conflict(client):
    client.post("/api/leads", json=PRIYA)
    r = client.post("/api/leads", json={**PRIYA, "name": "Someone Else", "phone": ""})
    assert r.status_code == 409


def test_update_search_stats_delete(client):
    lead = client.post("/api/leads", json=PRIYA).json()
    client.post("/api/leads", json={"name": "Arjun Mehta", "phone": "+91 91234 56789", "status": "won"})

    r = client.patch(f"/api/leads/{lead['id']}", json={"status": "qualified", "address": "22 MG Road"})
    assert r.status_code == 200 and r.json()["status"] == "qualified"

    assert [l["name"] for l in client.get("/api/leads", params={"q": "mg road"}).json()] == ["Priya Raman"]
    assert len(client.get("/api/leads", params={"status": "won"}).json()) == 1

    stats = client.get("/api/leads/stats").json()
    assert stats["total"] == 2 and stats["qualified"] == 1 and stats["won"] == 1

    assert client.delete(f"/api/leads/{lead['id']}").status_code == 204
    assert client.get(f"/api/leads/{lead['id']}").status_code == 404


def test_update_cannot_remove_all_contacts(client):
    lead = client.post("/api/leads", json={"name": "Phone Only", "phone": "+91 90000 00000"}).json()
    assert client.patch(f"/api/leads/{lead['id']}", json={"phone": ""}).status_code == 422


def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Lead Desk" in r.text
