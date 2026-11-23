"""Runs a full trader/admin workflow against an in-memory app and prints each request/response."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import create_app
from app.config import TestConfig

class Cfg(TestConfig):
    ADMIN_EMAIL, ADMIN_PASSWORD = "admin@exchange.local", "AdminPass123"
c = create_app(Cfg).test_client()

def call(method, url, token=None, **kw):
    r = getattr(c, method)(url, headers={"Authorization": "Bearer " + token} if token else {}, **kw)
    s = json.dumps(r.get_json())
    print(f"\n> {method.upper()} {url} {json.dumps(kw['json']) if kw.get('json') else ''}\n< {r.status_code} {s[:330]}{'...' if len(s) > 330 else ''}")
    return r.get_json()
s = call("post", "/signup", json={"name": "Trader One", "email": "trader@mail.com", "password": "password123"})["data"]
t = s["token"]
call("post", "/wallet/create", t, json={"coin": "USDT"})                 # 403: email not verified yet
call("post", "/verify-email", json={"token": s["verification_token"]})
call("post", "/wallet/create", t, json={"coin": "USDT"})
call("post", "/wallet/deposit", t, json={"coin": "USDT", "amount": 10000})
call("post", "/trade/buy", t, json={"coin": "BTC", "quantity": 0.1})
call("post", "/trade/buy", t, json={"coin": "ETH", "quantity": 100})     # 400: insufficient USDT
call("post", "/wallet/withdraw", t, json={"coin": "USDT", "amount": 99999})  # 400: no negative balance
a = call("post", "/login", json={"email": "admin@exchange.local", "password": "AdminPass123"})["data"]["token"]
call("put", "/admin/coins/1", a, json={"current_price": 70000})
call("get", "/portfolio", t)
call("post", "/trade/sell", t, json={"coin": "BTC", "quantity": 0.05})
call("get", "/transactions?type=sell", t)
call("get", "/admin/users", t)                                           # 403: admin only
call("get", "/admin/analytics", a)
