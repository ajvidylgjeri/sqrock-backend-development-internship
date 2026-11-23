from datetime import date, timedelta

import itertools

import pytest

from app import create_app
from app.config import TestConfig


@pytest.fixture()
def c():
    return create_app(TestConfig).test_client()


_n = itertools.count()


def signup(c, role, email=None, pw="password123"):
    email = email or f"{role}{next(_n)}@test.com"
    r = c.post("/signup", json={"name": "Test " + role, "email": email, "password": pw, "role": role})
    assert r.status_code == 201, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["data"]["token"]}


def project_payload(**kw):
    p = {"title": "Build a landing page", "category": "Web", "budget": 500, "description": "Responsive landing page for a small bakery shop.",
         "required_skills": ["html", "css"], "deadline": (date.today() + timedelta(days=30)).isoformat(), "experience_level": "intermediate"}
    p.update(kw)
    return p


def mk_project(c, h, **kw):
    r = c.post("/projects", json=project_payload(**kw), headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"]


def bid(c, h, pid, amount=450):
    return c.post(f"/projects/{pid}/proposal", json={"bid_amount": amount, "cover_letter": "I have built many similar sites and can deliver fast.", "delivery_time": 10}, headers=h)


def test_signup_login_validation(c):
    signup(c, "client", "a@test.com")
    assert c.post("/signup", json={"name": "x y", "email": "a@test.com", "password": "password123", "role": "client"}).status_code == 409
    assert c.post("/signup", json={"name": "xy", "email": "bad", "password": "password123", "role": "client"}).status_code == 400
    assert c.post("/signup", json={"name": "xy", "email": "b@test.com", "password": "short", "role": "client"}).status_code == 400
    assert c.post("/signup", json={"name": "xy", "email": "b@test.com", "password": "password123", "role": "admin"}).status_code == 400
    assert c.post("/signup", data="not json", content_type="text/plain").status_code == 400
    assert c.post("/login", json={"email": "a@test.com", "password": "password123"}).status_code == 200
    assert c.post("/login", json={"email": "a@test.com", "password": "nope"}).status_code == 401
    r = c.post("/login", json={"email": "a@test.com", "password": "password123"}).get_json()["data"]
    assert "password" not in r["user"]


def test_password_is_bcrypt_hashed(c):
    from app.models import User
    signup(c, "client", "h@test.com")
    with c.application.app_context():
        assert User.query.filter_by(email="h@test.com").first().password.startswith("$2")


def test_auth_required_and_bad_token(c):
    assert c.get("/projects").status_code == 401
    assert c.get("/projects", headers={"Authorization": "Bearer abc"}).status_code == 401


def test_role_restrictions(c):
    cl, fr = signup(c, "client"), signup(c, "freelancer")
    assert c.post("/projects", json=project_payload(), headers=fr).status_code == 403
    p = mk_project(c, cl)
    assert bid(c, cl, p["id"]).status_code == 403
    assert c.get("/my-proposals", headers=cl).status_code == 403
    assert c.get("/client/dashboard", headers=fr).status_code == 403
    assert c.get(f"/projects/{p['id']}/proposals", headers=fr).status_code == 403
    assert c.delete(f"/projects/{p['id']}", headers=fr).status_code == 403
    assert c.put(f"/project/{p['id']}/start", headers=fr).status_code == 403


def test_project_validation_and_ownership(c):
    cl, other = signup(c, "client"), signup(c, "client")
    assert c.post("/projects", json=project_payload(budget=-5), headers=cl).status_code == 400
    assert c.post("/projects", json=project_payload(deadline="2001-01-01"), headers=cl).status_code == 400
    assert c.post("/projects", json=project_payload(experience_level="god"), headers=cl).status_code == 400
    assert c.post("/projects", json=project_payload(title="x"), headers=cl).status_code == 400
    p = mk_project(c, cl)
    assert c.put(f"/projects/{p['id']}", json={"budget": 700}, headers=cl).get_json()["data"]["budget"] == 700
    assert c.put(f"/projects/{p['id']}", json={"budget": 700}, headers=other).status_code == 403
    assert c.delete(f"/projects/{p['id']}", headers=other).status_code == 403
    assert c.get("/projects/9999", headers=cl).status_code == 404
    assert c.delete(f"/projects/{p['id']}", headers=cl).status_code == 200
    assert c.get(f"/projects/{p['id']}", headers=cl).status_code == 404


def test_browse_search_filter(c):
    cl, fr = signup(c, "client"), signup(c, "freelancer")
    mk_project(c, cl, title="Logo design for cafe", category="Design", budget=100, required_skills="photoshop")
    mk_project(c, cl, title="Django REST API", category="Backend", budget=900, required_skills=["python", "django"])
    assert c.get("/projects", headers=fr).get_json()["total"] == 2
    assert c.get("/projects?category=design", headers=fr).get_json()["total"] == 1
    assert c.get("/projects?search=django", headers=fr).get_json()["total"] == 1
    assert c.get("/projects?min_budget=500", headers=fr).get_json()["total"] == 1
    assert c.get("/projects?search=zzz", headers=fr).get_json()["total"] == 0
    assert c.get("/projects?per_page=1&page=2", headers=fr).get_json()["data"].__len__() == 1
    assert c.get("/projects?min_budget=abc", headers=fr).status_code == 400


def test_full_workflow(c):
    cl, f1, f2 = signup(c, "client"), signup(c, "freelancer"), signup(c, "freelancer")
    p = mk_project(c, cl)
    pid = p["id"]
    r1, r2 = bid(c, f1, pid, 400).get_json()["data"], bid(c, f2, pid, 450).get_json()["data"]
    assert bid(c, f1, pid).status_code == 409
    assert c.post(f"/projects/{pid}/proposal", json={"bid_amount": -1, "cover_letter": "x", "delivery_time": 0}, headers=f2).status_code in (400, 409)
    assert len(c.get(f"/projects/{pid}/proposals", headers=cl).get_json()["data"]) == 2
    assert c.put(f"/proposal/{r1['id']}/accept", headers=f1).status_code == 403
    acc = c.put(f"/proposal/{r1['id']}/accept", headers=cl)
    assert acc.status_code == 200 and acc.get_json()["data"]["project"]["freelancer_id"] == r1["freelancer_id"]
    mine = c.get("/my-proposals", headers=f2).get_json()["data"]
    assert mine[0]["status"] == "rejected"
    assert c.put(f"/proposal/{r2['id']}/accept", headers=cl).status_code == 409
    assert c.delete(f"/proposal/{r1['id']}", headers=f1).status_code == 409     # accepted: cannot withdraw
    assert c.put(f"/projects/{pid}", json={"budget": 5}, headers=cl).status_code == 409
    assert c.put(f"/project/{pid}/complete", headers=cl).status_code == 409    # not started yet
    assert c.put(f"/project/{pid}/start", headers=cl).get_json()["data"]["project"]["status"] == "in_progress"
    assert c.put(f"/project/{pid}/start", headers=cl).status_code == 409
    assert c.get("/freelancer/dashboard", headers=f1).get_json()["data"]["active_projects"] == 1
    done = c.put(f"/project/{pid}/complete", headers=cl).get_json()["data"]
    assert done["project"]["status"] == "completed" and done["contract"]["completed_at"]
    assert c.put(f"/project/{pid}/cancel", headers=cl).status_code == 409
    d = c.get("/freelancer/dashboard", headers=f1).get_json()["data"]
    assert d == {"applied_projects": 1, "active_projects": 0, "completed_projects": 1, "accepted_proposals": 1, "total_earnings": 400.0}
    cd = c.get("/client/dashboard", headers=cl).get_json()["data"]
    assert cd["total_projects"] == 1 and cd["completed_projects"] == 1 and cd["total_proposals_received"] == 2


def test_reject_withdraw_cancel(c):
    cl, fr = signup(c, "client"), signup(c, "freelancer")
    pid = mk_project(c, cl)["id"]
    pr = bid(c, fr, pid).get_json()["data"]
    assert c.put(f"/proposal/{pr['id']}/reject", headers=cl).get_json()["data"]["status"] == "rejected"
    assert c.put(f"/proposal/{pr['id']}/reject", headers=cl).status_code == 409
    pid2 = mk_project(c, cl)["id"]
    pr2 = bid(c, fr, pid2).get_json()["data"]
    other = signup(c, "freelancer")
    assert c.delete(f"/proposal/{pr2['id']}", headers=other).status_code == 403
    assert c.delete(f"/proposal/{pr2['id']}", headers=fr).status_code == 200
    assert c.put(f"/project/{pid2}/cancel", headers=cl).get_json()["data"]["status"] == "cancelled"
    assert bid(c, fr, pid2).status_code == 409            # cancelled projects take no bids
    assert c.put(f"/project/{pid2}/cancel", headers=cl).status_code == 409


def test_cannot_delete_in_progress_and_cors_and_errors(c):
    cl, fr = signup(c, "client"), signup(c, "freelancer")
    pid = mk_project(c, cl)["id"]
    pr = bid(c, fr, pid).get_json()["data"]
    c.put(f"/proposal/{pr['id']}/accept", headers=cl)
    assert c.delete(f"/projects/{pid}", headers=cl).status_code == 409
    r = c.options("/projects", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
    assert c.get("/nope").get_json()["success"] is False
    assert c.patch("/projects", headers=cl).status_code == 405
