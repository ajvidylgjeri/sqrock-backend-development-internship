# Cryptocurrency Exchange Backend API

Sqrock IT Solutions — Backend Development Internship, Project Phase 2, **Task 4**.

Secure REST API for a (mock) cryptocurrency exchange: traders manage wallets, deposit / withdraw (mock), buy and sell coins at admin-set prices, review a portfolio with profit/loss and filter their transaction history; admins manage users, coins and see platform analytics.
Stack: **Python, Flask, SQLAlchemy, JWT (PyJWT), bcrypt, Flask-CORS**; SQLite by default, **MySQL** through `DATABASE_URL`. Money uses `Decimal` / `NUMERIC(28,8)`.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # set SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, export the variables
python run.py            # http://127.0.0.1:5000  (supported coins and the admin account are created on first start)
pytest -q                # 11 end-to-end tests
python docs/demo.py      # prints a full trader/admin workflow (saved in docs/demo_session.txt)
```
MySQL: `DATABASE_URL=mysql+pymysql://user:password@localhost:3306/exchange` (create the empty database first; tables are created on start — not tested against a live MySQL server here).

## Security
- bcrypt password hashing; JWT bearer tokens; the role is always read from the database, never trusted from the token; role can never be chosen at signup.
- Role middleware: `@auth_required("user")` vs `@auth_required("admin")` (admins cannot trade, users cannot reach /admin).
- Blocked users: login refused and existing tokens stop working immediately.
- Wallet ownership verification (`wallet_address` of another user → 403), transaction ownership checks.
- Prevent invalid transactions / negative balances: Decimal arithmetic, ≤ 8 decimal places, positive amounts only, balance checks, plus database `CHECK (available_balance >= 0)`. Failed withdrawals are logged as `failed` transactions.
- Mock email verification (token returned by `/signup`, confirmed with `/verify-email`; wallets and trading need a verified email).
- Rate limiting (global per IP, stricter on `/login` and `/signup`), CORS allow-list, validated input, uniform JSON errors without stack traces, secrets from environment variables.

## Endpoints (JSON; everything except /signup, /verify-email, /login, /health needs `Authorization: Bearer <token>`)
| Method & path | Role | Purpose |
|---|---|---|
| POST /signup, POST /verify-email, POST /login | public | register (role is always `user`), mock email verification, login |
| GET /coins | any | active supported coins and prices |
| POST /wallet/create | user | `{coin}` — one wallet per coin, address auto-generated |
| GET /wallet | user | own wallets (`?coin=BTC`) with available / locked balance |
| POST /wallet/deposit, /wallet/withdraw | user | `{coin or wallet_address, amount}` (mock funds) |
| POST /trade/buy, POST /trade/sell | user | `{coin, quantity}` at the current price, settled in USDT (auto-creates the coin wallet) |
| GET /holdings, GET /portfolio | user | balances; total value, average buy price, unrealized P/L, investment history |
| GET /transactions, GET /transactions/:id | user | filters `from`, `to` (YYYY-MM-DD), `coin`, `type`, pagination |
| GET /admin/users, /admin/wallets, /admin/trades, /admin/transactions | admin | platform-wide lists |
| PUT /admin/users/:id/block, /unblock | admin | block / unblock a trader |
| POST /admin/coins, PUT /admin/coins/:id, DELETE /admin/coins/:id | admin | manage supported coins and mock prices (coins with history are disabled, not removed; USDT is protected) |
| GET /admin/analytics | admin | users, wallets, trades, volumes, trades by coin |

Database tables: `users`, `wallets`, `supported_coins`, `trades`, `transactions`. Each trade writes two transactions (coin leg and USDT leg).

## Notes / limits
Prices are manually set mock values (no market feed); P/L covers coins acquired through trades (deposited coins have no known cost basis); two-factor auth, locked balances / open orders and hosting are not implemented. SQLite serialises writes; for MySQL under load, add row-level locking (`SELECT ... FOR UPDATE`) on wallet rows.
