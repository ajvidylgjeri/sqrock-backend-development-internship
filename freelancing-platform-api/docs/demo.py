"""Runs a full client/freelancer workflow against an in-memory app and prints each request/response."""
import json, sys, os
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import create_app
from app.config import TestConfig

c = create_app(TestConfig).test_client()
def call(method, url, token=None, **kw):
    h = {"Authorization": "Bearer " + token} if token else {}
    r = getattr(c, method)(url, headers=h, **kw)
    body = r.get_json()
    s = json.dumps(body)
    print(f"\n> {method.upper()} {url} {json.dumps(kw.get('json'))[:160] if kw.get('json') else ''}\n< {r.status_code} {s[:300]}{'...' if len(s) > 300 else ''}")
    return body
cl = call("post", "/signup", json={"name": "Acme Client", "email": "client@acme.com", "password": "password123", "role": "client"})["data"]["token"]
fr = call("post", "/signup", json={"name": "Jane Dev", "email": "jane@dev.io", "password": "password123", "role": "freelancer", "skills": ["python", "flask"]})["data"]["token"]
p = call("post", "/projects", cl, json={"title": "REST API for a bakery", "category": "backend", "budget": 800, "description": "Need a Flask REST API with JWT auth for orders.",
         "required_skills": ["python", "flask"], "deadline": (date.today() + timedelta(days=21)).isoformat(), "experience_level": "intermediate"})["data"]
call("get", "/projects?search=flask", fr)
pr = call("post", f"/projects/{p['id']}/proposal", fr, json={"bid_amount": 700, "cover_letter": "I have built several Flask APIs and can deliver in two weeks.", "delivery_time": 14})["data"]
call("post", "/projects", fr, json={})               # freelancer cannot create projects -> 403
call("put", f"/proposal/{pr['id']}/accept", cl)
call("put", f"/project/{p['id']}/start", cl)
call("put", f"/project/{p['id']}/complete", cl)
call("get", "/client/dashboard", cl)
call("get", "/freelancer/dashboard", fr)
