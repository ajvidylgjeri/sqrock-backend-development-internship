import secrets
from datetime import datetime, timezone
from decimal import Decimal

import bcrypt
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
Money = db.Numeric(28, 8)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def f(x):
    return float(x) if x is not None else None


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="user")      # user | admin
    status = db.Column(db.String(10), nullable=False, default="active")  # active | blocked
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    verification_token = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=now)

    def set_password(self, pw):
        self.password = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

    def check_password(self, pw):
        return bcrypt.checkpw(pw.encode(), self.password.encode())

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role, "status": self.status,
                "email_verified": self.email_verified, "created_at": self.created_at.isoformat()}


class Coin(db.Model):
    __tablename__ = "supported_coins"
    id = db.Column(db.Integer, primary_key=True)
    coin_name = db.Column(db.String(60), unique=True, nullable=False)
    coin_symbol = db.Column(db.String(10), unique=True, nullable=False)
    current_price = db.Column(Money, nullable=False)   # in USDT (mock)
    status = db.Column(db.String(10), nullable=False, default="active")  # active | inactive

    def to_dict(self):
        return {"id": self.id, "coin_name": self.coin_name, "coin_symbol": self.coin_symbol, "current_price": f(self.current_price), "status": self.status}


class Wallet(db.Model):
    __tablename__ = "wallets"
    __table_args__ = (db.UniqueConstraint("user_id", "coin_symbol", name="uq_wallet_user_coin"),
                      db.CheckConstraint("available_balance >= 0", name="ck_available_non_negative"),
                      db.CheckConstraint("locked_balance >= 0", name="ck_locked_non_negative"))
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    wallet_address = db.Column(db.String(64), unique=True, nullable=False, default=lambda: "0x" + secrets.token_hex(20))
    coin_symbol = db.Column(db.String(10), nullable=False)
    coin_name = db.Column(db.String(60), nullable=False)
    available_balance = db.Column(Money, nullable=False, default=Decimal("0"))
    locked_balance = db.Column(Money, nullable=False, default=Decimal("0"))
    created_at = db.Column(db.DateTime, default=now)

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "wallet_address": self.wallet_address, "coin_symbol": self.coin_symbol, "coin_name": self.coin_name,
                "available_balance": f(self.available_balance), "locked_balance": f(self.locked_balance), "created_at": self.created_at.isoformat()}


class Trade(db.Model):
    __tablename__ = "trades"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    coin_id = db.Column(db.Integer, db.ForeignKey("supported_coins.id"), nullable=False)
    trade_type = db.Column(db.String(4), nullable=False)  # buy | sell
    quantity = db.Column(Money, nullable=False)
    price = db.Column(Money, nullable=False)
    total_amount = db.Column(Money, nullable=False)
    created_at = db.Column(db.DateTime, default=now)
    coin = db.relationship("Coin")

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "coin": self.coin.coin_symbol, "trade_type": self.trade_type, "quantity": f(self.quantity),
                "price": f(self.price), "total_amount": f(self.total_amount), "created_at": self.created_at.isoformat()}


class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=False)
    transaction_type = db.Column(db.String(10), nullable=False, index=True)  # deposit|withdraw|buy|sell
    coin_symbol = db.Column(db.String(10), nullable=False, index=True)
    amount = db.Column(Money, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="completed")  # pending|completed|failed
    timestamp = db.Column(db.DateTime, default=now, index=True)

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "wallet_id": self.wallet_id, "transaction_type": self.transaction_type,
                "coin_symbol": self.coin_symbol, "amount": f(self.amount), "status": self.status, "timestamp": self.timestamp.isoformat()}
