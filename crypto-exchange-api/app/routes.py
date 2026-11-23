import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, g, request
from sqlalchemy import func

from .models import Coin, Trade, Transaction, User, Wallet, db, f, now
from .utils import ApiError, auth_required, body, create_token, EMAIL_RE, money, ok, text

bp = Blueprint("api", __name__)
QUOTE = "USDT"
D0 = Decimal("0")


def q8(x):
    return Decimal(x).quantize(Decimal("0.00000001"))


@bp.get("/health")
def health():
    return ok({"status": "ok"})


# ---------------- auth ----------------
@bp.post("/signup")
def signup():
    d = body()
    name, email = text(d, "name", 2, 100), text(d, "email", 5, 120).lower()
    pw = d.get("password")
    if not EMAIL_RE.match(email):
        raise ApiError("Enter a valid email address")
    if not isinstance(pw, str) or len(pw) < 8 or len(pw) > 72:
        raise ApiError("Password must be 8-72 characters")
    if User.query.filter_by(email=email).first():
        raise ApiError("Email already registered", 409)
    u = User(name=name, email=email, role="user", verification_token=secrets.token_urlsafe(24))   # role can never be chosen at signup
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()
    # Mock e-mail: in production the token would be e-mailed; here it is returned so the flow can be tested.
    return ok({"user": u.to_dict(), "token": create_token(u), "verification_token": u.verification_token,
               "note": "Mock email verification: POST /verify-email with this token"}, 201)


@bp.post("/verify-email")
def verify_email():
    t = text(body(), "token", 10, 64)
    u = User.query.filter_by(verification_token=t).first()
    if not u:
        raise ApiError("Invalid verification token", 400)
    u.email_verified, u.verification_token = True, None
    db.session.commit()
    return ok(u.to_dict())


@bp.post("/login")
def login():
    d = body()
    u = User.query.filter_by(email=str(d.get("email", "")).strip().lower()).first()
    if not u or not isinstance(d.get("password"), str) or not u.check_password(d["password"]):
        raise ApiError("Invalid email or password", 401)
    if u.status == "blocked":
        raise ApiError("This account has been blocked", 403)
    return ok({"user": u.to_dict(), "token": create_token(u)})


def verified_user():
    if not g.user.email_verified:
        raise ApiError("Verify your email address first (POST /verify-email)", 403)


# ---------------- wallets ----------------
def active_coin(symbol):
    symbol = str(symbol or "").strip().upper()
    c = Coin.query.filter_by(coin_symbol=symbol).first()
    if not c:
        raise ApiError(f"Unsupported coin '{symbol}'", 404)
    if c.status != "active":
        raise ApiError(f"{symbol} is currently disabled", 409)
    return c


def my_wallet(symbol, create=False):
    w = Wallet.query.filter_by(user_id=g.user.id, coin_symbol=symbol).first()
    if not w and create:
        c = Coin.query.filter_by(coin_symbol=symbol).first()
        w = Wallet(user_id=g.user.id, coin_symbol=symbol, coin_name=c.coin_name, available_balance=D0, locked_balance=D0)
        db.session.add(w)
        db.session.flush()
    return w


def resolve_wallet(d):
    """Find the caller's wallet by wallet_address (ownership verified) or by coin symbol."""
    if d.get("wallet_address"):
        w = Wallet.query.filter_by(wallet_address=str(d["wallet_address"])).first()
        if not w:
            raise ApiError("Wallet not found", 404)
        if w.user_id != g.user.id:
            raise ApiError("This wallet does not belong to you", 403)
        return w
    sym = str(d.get("coin", "")).strip().upper()
    if not sym:
        raise ApiError("Provide 'wallet_address' or 'coin'")
    w = my_wallet(sym)
    if not w:
        raise ApiError(f"You have no {sym} wallet; create one first", 404)
    return w


def log_tx(w, ttype, amount, status="completed"):
    t = Transaction(user_id=w.user_id, wallet_id=w.id, transaction_type=ttype, coin_symbol=w.coin_symbol, amount=amount, status=status)
    db.session.add(t)
    return t


@bp.post("/wallet/create")
@auth_required("user")
def wallet_create():
    verified_user()
    c = active_coin(body().get("coin"))
    if my_wallet(c.coin_symbol):
        raise ApiError(f"You already have a {c.coin_symbol} wallet", 409)
    w = my_wallet(c.coin_symbol, create=True)
    db.session.commit()
    return ok(w.to_dict(), 201)


@bp.get("/wallet")
@auth_required("user")
def wallet_list():
    q = Wallet.query.filter_by(user_id=g.user.id)
    if request.args.get("coin"):
        q = q.filter_by(coin_symbol=request.args["coin"].upper())
    return ok([w.to_dict() for w in q.order_by(Wallet.id).all()])


@bp.post("/wallet/deposit")
@auth_required("user")
def deposit():
    verified_user()
    d = body()
    w = resolve_wallet(d)
    amount = money(d, "amount", "1000000000")
    active_coin(w.coin_symbol)
    w.available_balance = q8(w.available_balance + amount)
    log_tx(w, "deposit", amount)
    db.session.commit()
    return ok({"wallet": w.to_dict()}, 200)


@bp.post("/wallet/withdraw")
@auth_required("user")
def withdraw():
    verified_user()
    d = body()
    w = resolve_wallet(d)
    amount = money(d, "amount", "1000000000")
    if amount > w.available_balance:
        t = log_tx(w, "withdraw", amount, "failed")
        db.session.commit()
        raise ApiError(f"Insufficient available balance ({f(w.available_balance)} {w.coin_symbol})", 400)
    w.available_balance = q8(w.available_balance - amount)
    log_tx(w, "withdraw", amount)
    db.session.commit()
    return ok({"wallet": w.to_dict()})


# ---------------- trading ----------------
def do_trade(side):
    verified_user()
    d = body()
    coin = active_coin(d.get("coin"))
    if coin.coin_symbol == QUOTE:
        raise ApiError(f"{QUOTE} is the quote currency and cannot be traded against itself")
    qty = money(d, "quantity", "1000000000")
    price = Decimal(coin.current_price)
    total = q8(qty * price)
    if total <= 0:
        raise ApiError("Trade total is too small")
    usdt = my_wallet(QUOTE)
    if not usdt:
        raise ApiError(f"Create and fund a {QUOTE} wallet first", 400)
    cw = my_wallet(coin.coin_symbol, create=True)
    if side == "buy":
        if usdt.available_balance < total:
            raise ApiError(f"Insufficient {QUOTE}: need {f(total)}, available {f(usdt.available_balance)}", 400)
        usdt.available_balance = q8(usdt.available_balance - total)
        cw.available_balance = q8(cw.available_balance + qty)
    else:
        if cw.available_balance < qty:
            raise ApiError(f"Insufficient {coin.coin_symbol}: need {f(qty)}, available {f(cw.available_balance)}", 400)
        cw.available_balance = q8(cw.available_balance - qty)
        usdt.available_balance = q8(usdt.available_balance + total)
    tr = Trade(user_id=g.user.id, coin_id=coin.id, trade_type=side, quantity=qty, price=price, total_amount=total)
    db.session.add(tr)
    log_tx(cw, side, qty)
    log_tx(usdt, "sell" if side == "buy" else "buy", total)   # the quote-currency leg of the trade
    db.session.commit()
    return ok({"trade": tr.to_dict(), "wallets": [usdt.to_dict(), cw.to_dict()]}, 201)


@bp.post("/trade/buy")
@auth_required("user")
def buy():
    return do_trade("buy")


@bp.post("/trade/sell")
@auth_required("user")
def sell():
    return do_trade("sell")


def positions(user_id):
    """Average cost per coin from the user's trade history (moving-average method)."""
    pos = {}
    for t in Trade.query.filter_by(user_id=user_id).order_by(Trade.id).all():
        p = pos.setdefault(t.coin.coin_symbol, {"qty": D0, "cost": D0})
        if t.trade_type == "buy":
            p["qty"] += t.quantity
            p["cost"] += t.total_amount
        elif p["qty"] > 0:
            share = min(t.quantity, p["qty"]) / p["qty"]
            p["cost"] -= p["cost"] * share
            p["qty"] -= min(t.quantity, p["qty"])
    return pos


@bp.get("/holdings")
@auth_required("user")
def holdings():
    rows = []
    for w in Wallet.query.filter_by(user_id=g.user.id).all():
        total = w.available_balance + w.locked_balance
        if total > 0:
            c = Coin.query.filter_by(coin_symbol=w.coin_symbol).first()
            rows.append({"coin": w.coin_symbol, "quantity": f(total), "available": f(w.available_balance), "locked": f(w.locked_balance),
                         "price": f(c.current_price), "value_usdt": f(q8(total * c.current_price))})
    return ok(rows)


@bp.get("/portfolio")
@auth_required("user")
def portfolio():
    pos, items, total_value, total_cost = positions(g.user.id), [], D0, D0
    for w in Wallet.query.filter_by(user_id=g.user.id).order_by(Wallet.id).all():
        qty = w.available_balance + w.locked_balance
        if qty <= 0:
            continue
        c = Coin.query.filter_by(coin_symbol=w.coin_symbol).first()
        value = q8(qty * c.current_price)
        total_value += value
        row = {"coin": w.coin_symbol, "quantity": f(qty), "price": f(c.current_price), "value_usdt": f(value)}
        p = pos.get(w.coin_symbol)
        if p and p["qty"] > 0:   # P/L covers the quantity acquired through trades (deposited coins have no known cost)
            cost = q8(p["cost"])
            pl_value = q8(p["qty"] * c.current_price)
            row.update({"traded_quantity": f(p["qty"]), "avg_buy_price": f(q8(cost / p["qty"])), "cost_basis_usdt": f(cost),
                        "unrealized_pl_usdt": f(pl_value - cost), "unrealized_pl_pct": round(float((pl_value - cost) / cost * 100), 2) if cost else 0.0})
            total_cost += cost
        items.append(row)
    invested = Trade.query.with_entities(func.coalesce(func.sum(Trade.total_amount), 0)).filter_by(user_id=g.user.id, trade_type="buy").scalar()
    return ok({"total_value_usdt": f(total_value), "holdings": items, "total_invested_usdt": f(Decimal(invested)),
               "investment_history": [t.to_dict() for t in Trade.query.filter_by(user_id=g.user.id).order_by(Trade.id.desc()).limit(20)]})


# ---------------- transactions ----------------
def parse_day(key):
    v = request.args.get(key)
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ApiError(f"'{key}' must be an ISO date (YYYY-MM-DD)")


def tx_query(q):
    if request.args.get("coin"):
        q = q.filter(Transaction.coin_symbol == request.args["coin"].upper())
    if request.args.get("type"):
        t = request.args["type"].lower()
        if t not in ("deposit", "withdraw", "buy", "sell"):
            raise ApiError("'type' must be deposit, withdraw, buy or sell")
        q = q.filter(Transaction.transaction_type == t)
    a, b = parse_day("from"), parse_day("to")
    if a:
        q = q.filter(Transaction.timestamp >= datetime.combine(a, datetime.min.time()))
    if b:
        q = q.filter(Transaction.timestamp < datetime.combine(b + timedelta(days=1), datetime.min.time()))
    return q


def paginate(q, order):
    try:
        page, per = max(1, int(request.args.get("page", 1))), min(100, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        raise ApiError("'page' and 'per_page' must be integers")
    return q.count(), q.order_by(*order).offset((page - 1) * per).limit(per).all(), page, per


@bp.get("/transactions")
@auth_required("user")
def transactions():
    total, items, page, per = paginate(tx_query(Transaction.query.filter_by(user_id=g.user.id)), (Transaction.timestamp.desc(), Transaction.id.desc()))
    return ok([t.to_dict() for t in items], page=page, per_page=per, total=total)


@bp.get("/transactions/<int:tid>")
@auth_required("user")
def transaction_detail(tid):
    t = db.session.get(Transaction, tid)
    if not t:
        raise ApiError("Transaction not found", 404)
    if t.user_id != g.user.id:
        raise ApiError("This transaction does not belong to you", 403)
    return ok(t.to_dict())


# ---------------- admin ----------------
@bp.get("/admin/users")
@auth_required("admin")
def admin_users():
    return ok([u.to_dict() for u in User.query.order_by(User.id).all()])


def set_status(uid, status):
    u = db.session.get(User, uid)
    if not u:
        raise ApiError("User not found", 404)
    if u.role == "admin":
        raise ApiError("Administrator accounts cannot be blocked", 409)
    u.status = status
    db.session.commit()
    return ok(u.to_dict())


@bp.put("/admin/users/<int:uid>/block")
@auth_required("admin")
def admin_block(uid):
    return set_status(uid, "blocked")


@bp.put("/admin/users/<int:uid>/unblock")
@auth_required("admin")
def admin_unblock(uid):
    return set_status(uid, "active")


@bp.get("/admin/wallets")
@auth_required("admin")
def admin_wallets():
    total, items, page, per = paginate(Wallet.query, (Wallet.id,))
    return ok([w.to_dict() for w in items], page=page, per_page=per, total=total)


@bp.get("/admin/trades")
@auth_required("admin")
def admin_trades():
    total, items, page, per = paginate(Trade.query, (Trade.id.desc(),))
    return ok([t.to_dict() for t in items], page=page, per_page=per, total=total)


@bp.get("/admin/transactions")
@auth_required("admin")
def admin_transactions():
    total, items, page, per = paginate(tx_query(Transaction.query), (Transaction.timestamp.desc(), Transaction.id.desc()))
    return ok([t.to_dict() for t in items], page=page, per_page=per, total=total)


def coin_fields(d, partial=False):
    out = {}
    if not partial or "coin_name" in d:
        out["coin_name"] = text(d, "coin_name", 2, 60)
    if not partial or "coin_symbol" in d:
        sym = text(d, "coin_symbol", 2, 10).upper()
        if not sym.isalnum():
            raise ApiError("'coin_symbol' must be letters/digits only")
        out["coin_symbol"] = sym
    if not partial or "current_price" in d:
        out["current_price"] = money(d, "current_price")
    if "status" in d:
        if d["status"] not in ("active", "inactive"):
            raise ApiError("'status' must be active or inactive")
        out["status"] = d["status"]
    return out


@bp.get("/coins")
@auth_required()
def coins():
    return ok([c.to_dict() for c in Coin.query.filter_by(status="active").order_by(Coin.id)])


@bp.post("/admin/coins")
@auth_required("admin")
def admin_add_coin():
    fields = coin_fields(body())
    if Coin.query.filter((Coin.coin_symbol == fields["coin_symbol"]) | (Coin.coin_name == fields["coin_name"])).first():
        raise ApiError("A coin with this name or symbol already exists", 409)
    c = Coin(**fields)
    db.session.add(c)
    db.session.commit()
    return ok(c.to_dict(), 201)


@bp.put("/admin/coins/<int:cid>")
@auth_required("admin")
def admin_edit_coin(cid):
    c = db.session.get(Coin, cid)
    if not c:
        raise ApiError("Coin not found", 404)
    fields = coin_fields(body(), partial=True)
    if not fields:
        raise ApiError("No fields supplied")
    if c.coin_symbol == QUOTE and ("coin_symbol" in fields or fields.get("status") == "inactive" or ("current_price" in fields and fields["current_price"] != 1)):
        raise ApiError(f"{QUOTE} is the quote currency (fixed price 1, cannot be renamed or disabled)", 409)
    for k, v in fields.items():
        setattr(c, k, v)
    db.session.commit()
    return ok(c.to_dict())


@bp.delete("/admin/coins/<int:cid>")
@auth_required("admin")
def admin_delete_coin(cid):
    c = db.session.get(Coin, cid)
    if not c:
        raise ApiError("Coin not found", 404)
    if c.coin_symbol == QUOTE:
        raise ApiError(f"{QUOTE} is the quote currency and cannot be removed", 409)
    if Trade.query.filter_by(coin_id=c.id).first() or Wallet.query.filter_by(coin_symbol=c.coin_symbol).first():
        c.status = "inactive"          # keep history intact: soft-delete
        db.session.commit()
        return ok({"deleted": False, "coin": c.to_dict(), "note": "Coin has wallets/trades, so it was disabled instead of removed"})
    db.session.delete(c)
    db.session.commit()
    return ok({"deleted": True, "id": cid})


@bp.get("/admin/analytics")
@auth_required("admin")
def admin_analytics():
    today = datetime.combine(date.today(), datetime.min.time())
    vol = Trade.query.with_entities(func.coalesce(func.sum(Trade.total_amount), 0)).scalar()
    vol24 = Trade.query.with_entities(func.coalesce(func.sum(Trade.total_amount), 0)).filter(Trade.created_at >= now() - timedelta(hours=24)).scalar()
    per_coin = (db.session.query(Coin.coin_symbol, func.count(Trade.id), func.coalesce(func.sum(Trade.total_amount), 0)).join(Trade, Trade.coin_id == Coin.id)
                .group_by(Coin.coin_symbol).all())
    return ok({"users": User.query.filter_by(role="user").count(), "blocked_users": User.query.filter_by(status="blocked").count(),
               "wallets": Wallet.query.count(), "trades": Trade.query.count(), "transactions": Transaction.query.count(),
               "trade_volume_usdt": f(Decimal(vol)), "trade_volume_24h_usdt": f(Decimal(vol24)),
               "new_users_today": User.query.filter(User.created_at >= today).count(),
               "trades_by_coin": [{"coin": s, "trades": n, "volume_usdt": f(Decimal(v))} for s, n, v in per_coin],
               "transactions_by_type": {t: n for t, n in db.session.query(Transaction.transaction_type, func.count(Transaction.id)).group_by(Transaction.transaction_type)}})
