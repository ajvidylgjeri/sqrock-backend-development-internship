import itertools

import pytest

from app import create_app
from app.config import TestConfig
from app.models import User, Wallet, db

_n = itertools.count()


class Cfg(TestConfig):
    ADMIN_EMAIL = "admin@test.com"
    ADMIN_PASSWORD = "AdminPass123"


@pytest.fixture()
def c():
    return create_app(Cfg).test_client()


def H(r):
    return {"Authorization": "Bearer " + r.get_json()["data"]["token"]}


def user(c, verify=True):
    email = f"u{next(_n)}@test.com"
    r = c.post("/signup", json={"name": "Trader", "email": email, "password": "password123"})
    assert r.status_code == 201, r.get_json()
    if verify:
        assert c.post("/verify-email", json={"token": r.get_json()["data"]["verification_token"]}).status_code == 200
    return H(r)


def admin(c):
    return H(c.post("/login", json={"email": "admin@test.com", "password": "AdminPass123"}))


def fund(c, h, amount=10000, coin="USDT"):
    c.post("/wallet/create", json={"coin": coin}, headers=h)
    r = c.post("/wallet/deposit", json={"coin": coin, "amount": amount}, headers=h)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["wallet"]


def test_auth_and_validation(c):
    assert c.post("/signup", json={"name": "x", "email": "bad", "password": "password123"}).status_code == 400
    assert c.post("/signup", json={"name": "xy", "email": "a@b.co", "password": "short"}).status_code == 400
    r = c.post("/signup", json={"name": "Eve", "email": "eve@test.com", "password": "password123", "role": "admin"})
    assert r.get_json()["data"]["user"]["role"] == "user"                    # role cannot be chosen
    assert c.post("/signup", json={"name": "Eve", "email": "eve@test.com", "password": "password123"}).status_code == 409
    assert c.post("/login", json={"email": "eve@test.com", "password": "wrongpass1"}).status_code == 401
    assert c.post("/login", json={"email": "eve@test.com", "password": "password123"}).status_code == 200
    assert c.get("/wallet").status_code == 401
    assert c.get("/wallet", headers={"Authorization": "Bearer junk"}).status_code == 401
    with c.application.app_context():
        assert User.query.filter_by(email="eve@test.com").first().password.startswith("$2")


def test_email_verification_required(c):
    h = user(c, verify=False)
    assert c.post("/wallet/create", json={"coin": "USDT"}, headers=h).status_code == 403
    assert c.post("/verify-email", json={"token": "wrong-token-value"}).status_code == 400


def test_wallet_flow_and_validation(c):
    h = user(c)
    w = c.post("/wallet/create", json={"coin": "btc"}, headers=h).get_json()["data"]
    assert w["coin_symbol"] == "BTC" and w["wallet_address"].startswith("0x") and w["available_balance"] == 0
    assert c.post("/wallet/create", json={"coin": "BTC"}, headers=h).status_code == 409
    assert c.post("/wallet/create", json={"coin": "DOGE"}, headers=h).status_code == 404
    assert c.post("/wallet/deposit", json={"coin": "BTC", "amount": 1.5}, headers=h).get_json()["data"]["wallet"]["available_balance"] == 1.5
    for bad in (0, -1, "abc", 0.000000001, None, True):
        assert c.post("/wallet/deposit", json={"coin": "BTC", "amount": bad}, headers=h).status_code == 400, bad
    assert c.post("/wallet/withdraw", json={"coin": "BTC", "amount": 2}, headers=h).status_code == 400      # no negative balance
    assert c.post("/wallet/withdraw", json={"coin": "BTC", "amount": 0.5}, headers=h).get_json()["data"]["wallet"]["available_balance"] == 1.0
    assert c.post("/wallet/withdraw", json={"coin": "ETH", "amount": 1}, headers=h).status_code == 404     # no such wallet
    assert len(c.get("/wallet", headers=h).get_json()["data"]) == 1
    types = [t["status"] for t in c.get("/transactions?coin=BTC", headers=h).get_json()["data"]]
    assert sorted(types) == ["completed", "completed", "failed"]                                            # failed withdraw logged


def test_wallet_ownership(c):
    a, b = user(c), user(c)
    wa = fund(c, a, 100)
    assert c.post("/wallet/withdraw", json={"wallet_address": wa["wallet_address"], "amount": 1}, headers=b).status_code == 403
    assert c.post("/wallet/deposit", json={"wallet_address": wa["wallet_address"], "amount": 1}, headers=b).status_code == 403
    assert c.post("/wallet/withdraw", json={"wallet_address": wa["wallet_address"], "amount": 1}, headers=a).status_code == 200
    assert c.post("/wallet/withdraw", json={"wallet_address": "0xnope", "amount": 1}, headers=a).status_code == 404
    assert c.get("/wallet", headers=b).get_json()["data"] == []


def test_buy_sell_and_portfolio(c):
    h = user(c)
    assert c.post("/trade/buy", json={"coin": "BTC", "quantity": 0.1}, headers=h).status_code == 400       # no USDT wallet
    fund(c, h, 10000)
    r = c.post("/trade/buy", json={"coin": "BTC", "quantity": 0.1}, headers=h)
    assert r.status_code == 201
    d = r.get_json()["data"]
    assert d["trade"]["total_amount"] == 6500 and d["trade"]["price"] == 65000
    bal = {w["coin_symbol"]: w["available_balance"] for w in c.get("/wallet", headers=h).get_json()["data"]}
    assert bal == {"USDT": 3500.0, "BTC": 0.1}
    assert c.post("/trade/buy", json={"coin": "BTC", "quantity": 1}, headers=h).status_code == 400         # insufficient USDT
    assert c.post("/trade/sell", json={"coin": "BTC", "quantity": 0.5}, headers=h).status_code == 400      # insufficient BTC
    assert c.post("/trade/buy", json={"coin": "USDT", "quantity": 1}, headers=h).status_code == 400
    assert c.post("/trade/buy", json={"coin": "XYZ", "quantity": 1}, headers=h).status_code == 404
    assert c.post("/trade/buy", json={"coin": "BTC", "quantity": -1}, headers=h).status_code == 400
    a = admin(c)
    assert c.put("/admin/coins/1", json={"current_price": 70000}, headers=a).status_code == 200
    p = c.get("/portfolio", headers=h).get_json()["data"]
    btc = [x for x in p["holdings"] if x["coin"] == "BTC"][0]
    assert btc["avg_buy_price"] == 65000 and btc["unrealized_pl_usdt"] == 500 and btc["unrealized_pl_pct"] == 7.69
    assert p["total_value_usdt"] == 3500 + 7000 and p["total_invested_usdt"] == 6500
    assert c.post("/trade/sell", json={"coin": "BTC", "quantity": 0.05}, headers=h).status_code == 201
    bal = {x["coin"]: x["quantity"] for x in c.get("/holdings", headers=h).get_json()["data"]}
    assert bal == {"USDT": 7000.0, "BTC": 0.05}
    btc = [x for x in c.get("/portfolio", headers=h).get_json()["data"]["holdings"] if x["coin"] == "BTC"][0]
    assert btc["avg_buy_price"] == 65000 and btc["unrealized_pl_usdt"] == 250
    assert len(c.get("/portfolio", headers=h).get_json()["data"]["investment_history"]) == 2


def test_never_negative_balance_at_db_level(c):
    h = user(c)
    w = fund(c, h, 5)
    with c.application.app_context():
        wallet = db.session.get(Wallet, w["id"])
        wallet.available_balance = -1
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


def test_transactions_filters_and_privacy(c):
    a, b = user(c), user(c)
    fund(c, a, 1000)
    c.post("/trade/buy", json={"coin": "ETH", "quantity": 0.1}, headers=a)
    allt = c.get("/transactions", headers=a).get_json()
    assert allt["total"] == 3                                    # deposit + buy (ETH leg) + sell (USDT leg)
    assert c.get("/transactions?type=buy", headers=a).get_json()["total"] == 1
    assert c.get("/transactions?coin=eth", headers=a).get_json()["total"] == 1
    assert c.get("/transactions?type=bogus", headers=a).status_code == 400
    assert c.get("/transactions?from=2999-01-01", headers=a).get_json()["total"] == 0
    assert c.get("/transactions?from=2000-01-01&to=2999-01-01", headers=a).get_json()["total"] == 3
    assert c.get("/transactions?from=notadate", headers=a).status_code == 400
    tid = allt["data"][0]["id"]
    assert c.get(f"/transactions/{tid}", headers=a).status_code == 200
    assert c.get(f"/transactions/{tid}", headers=b).status_code == 403
    assert c.get("/transactions/99999", headers=a).status_code == 404
    assert c.get("/transactions", headers=b).get_json()["total"] == 0


def test_role_separation(c):
    u, a = user(c), admin(c)
    for path in ("/admin/users", "/admin/wallets", "/admin/trades", "/admin/transactions", "/admin/analytics"):
        assert c.get(path, headers=u).status_code == 403, path
        assert c.get(path, headers=a).status_code == 200, path
    assert c.post("/admin/coins", json={"coin_name": "X", "coin_symbol": "XX", "current_price": 1}, headers=u).status_code == 403
    for path in ("/wallet", "/portfolio", "/holdings", "/transactions"):
        assert c.get(path, headers=a).status_code == 403, path       # admins do not trade


def test_admin_coin_management(c):
    a = admin(c)
    r = c.post("/admin/coins", json={"coin_name": "Dogecoin", "coin_symbol": "doge", "current_price": 0.15}, headers=a)
    assert r.status_code == 201 and r.get_json()["data"]["coin_symbol"] == "DOGE"
    cid = r.get_json()["data"]["id"]
    assert c.post("/admin/coins", json={"coin_name": "Dogecoin 2", "coin_symbol": "DOGE", "current_price": 1}, headers=a).status_code == 409
    assert c.post("/admin/coins", json={"coin_name": "Bad", "coin_symbol": "B@D", "current_price": 1}, headers=a).status_code == 400
    assert c.put(f"/admin/coins/{cid}", json={"current_price": -3}, headers=a).status_code == 400
    assert c.put(f"/admin/coins/{cid}", json={"status": "inactive"}, headers=a).get_json()["data"]["status"] == "inactive"
    h = user(c)
    fund(c, h, 100)
    assert c.post("/trade/buy", json={"coin": "DOGE", "quantity": 10}, headers=h).status_code == 409      # disabled
    c.put(f"/admin/coins/{cid}", json={"status": "active"}, headers=a)
    assert c.post("/trade/buy", json={"coin": "DOGE", "quantity": 10}, headers=h).status_code == 201
    out = c.delete(f"/admin/coins/{cid}", headers=a).get_json()["data"]
    assert out["deleted"] is False and out["coin"]["status"] == "inactive"                               # soft delete keeps history
    c.post("/admin/coins", json={"coin_name": "Temp", "coin_symbol": "TMP", "current_price": 2}, headers=a)
    tid = [x for x in c.get("/coins", headers=a).get_json()["data"] if x["coin_symbol"] == "TMP"][0]["id"]
    assert c.delete(f"/admin/coins/{tid}", headers=a).get_json()["data"]["deleted"] is True
    assert c.delete("/admin/coins/5", headers=a).status_code == 409                                       # USDT is protected
    assert c.put("/admin/coins/5", json={"current_price": 2}, headers=a).status_code == 409
    assert c.delete("/admin/coins/9999", headers=a).status_code == 404


def test_block_unblock_and_analytics(c):
    a = admin(c)
    r = c.post("/signup", json={"name": "Bad Actor", "email": "bad@test.com", "password": "password123"})
    h, uid = H(r), r.get_json()["data"]["user"]["id"]
    assert c.put(f"/admin/users/{uid}/block", headers=a).get_json()["data"]["status"] == "blocked"
    assert c.get("/wallet", headers=h).status_code == 403                    # existing token stops working
    assert c.post("/login", json={"email": "bad@test.com", "password": "password123"}).status_code == 403
    assert c.put(f"/admin/users/{uid}/unblock", headers=a).status_code == 200
    assert c.post("/login", json={"email": "bad@test.com", "password": "password123"}).status_code == 200
    assert c.put("/admin/users/1/block", headers=a).status_code == 409       # admin cannot be blocked
    assert c.put("/admin/users/999/block", headers=a).status_code == 404
    t = user(c)
    fund(c, t, 1000)
    c.post("/trade/buy", json={"coin": "SOL", "quantity": 2}, headers=t)
    an = c.get("/admin/analytics", headers=a).get_json()["data"]
    assert an["trades"] == 1 and an["trade_volume_usdt"] == 300 and an["trades_by_coin"][0]["coin"] == "SOL" and an["users"] == 2
    assert c.get("/admin/trades", headers=a).get_json()["total"] == 1


def test_rate_limit_and_errors():
    class Tight(Cfg):
        AUTH_RATE_LIMIT_PER_MINUTE = 3
    c = create_app(Tight).test_client()
    codes = [c.post("/login", json={"email": "x@y.zz", "password": "whatever1"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    c2 = create_app(Cfg).test_client()
    assert c2.get("/nothing").get_json()["success"] is False
    assert c2.post("/login", data="x", content_type="text/plain").status_code == 400
    r = c2.options("/wallet", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
