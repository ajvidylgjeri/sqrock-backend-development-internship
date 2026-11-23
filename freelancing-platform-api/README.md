# Freelancing Platform Backend API

Sqrock IT Solutions — Backend Development Internship, Project Phase 2, **Task 2**.

REST API for a freelancing marketplace: clients post projects, freelancers bid, clients accept / reject proposals and manage the project lifecycle.
Stack: **Python, Flask, SQLAlchemy, JWT (PyJWT), bcrypt, Flask-CORS**; SQLite by default, **MySQL** via `DATABASE_URL`.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit SECRET_KEY etc., then export the variables (or set them in your host)
python run.py                   # http://127.0.0.1:5000
pytest -q                       # 9 end-to-end tests
python docs/demo.py             # prints a complete client/freelancer workflow (saved in docs/demo_session.txt)
```
MySQL: `DATABASE_URL=mysql+pymysql://user:password@localhost:3306/freelance` (create the empty database first; tables are created on start — not tested against a live MySQL server here).

## Security
bcrypt password hashing · JWT bearer auth · role middleware (`@auth_required("client")`) · input validation on every body/query · uniform JSON errors with no stack traces ·
secrets from environment variables · CORS allow-list (`CORS_ORIGINS`) · per-IP rate limiting · ownership checks (a client can only touch their own projects; 403 otherwise).

## Workflow
`open` → client accepts a proposal (freelancer assigned, other bids rejected, contract `pending`) → `/start` → `in_progress` → `/complete` → `completed`.
`/cancel` is possible from `open` or `in_progress`. Edits are blocked once a freelancer is assigned; bids are only accepted for open, unassigned projects.

## Endpoints (JSON; all except /signup, /login, /health need `Authorization: Bearer <token>`)
| Method & path | Who | Purpose |
|---|---|---|
| POST /signup, POST /login | public | `role` = client or freelancer chosen at signup |
| POST /projects | client | create (title, category, budget, description, required_skills, deadline, experience_level) |
| GET /projects | any | browse; `search`, `category`, `level`, `min_budget`, `max_budget`, `status` (default open, `all`), `mine=1`, `page`, `per_page` |
| GET /projects/:id | any | detail + proposal_count |
| PUT /projects/:id, DELETE /projects/:id | owning client | edit / delete |
| POST /projects/:id/proposal | freelancer | bid_amount, cover_letter, delivery_time (days); one bid per project |
| GET /my-proposals | freelancer | own proposals with project status |
| GET /projects/:id/proposals | owning client | all proposals for a project |
| PUT /proposal/:id/accept, PUT /proposal/:id/reject | owning client | decide |
| DELETE /proposal/:id | freelancer (owner) | withdraw a pending proposal |
| PUT /project/:id/start, /complete, /cancel | owning client | lifecycle |
| GET /client/dashboard, GET /freelancer/dashboard | client / freelancer | counters (freelancer also gets total_earnings) |

Database: `users`, `projects`, `proposals` (unique per project+freelancer), `contracts` — see `app/models.py`.

## Not included
Bonus features (messaging, reviews, uploads, payments) and a hosted live link: the code is ready for any Python host (`gunicorn run:app`), but it has not been deployed.
