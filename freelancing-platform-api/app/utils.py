import re
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from .models import User, db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def ok(data=None, status=200, **extra):
    return jsonify({"success": True, "data": data, **extra}), status


def fail(message, status=400):
    return jsonify({"success": False, "error": message}), status


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object")
    return data


def text(d, key, min_len=1, max_len=255, required=True):
    v = d.get(key)
    if v is None or v == "":
        if required:
            raise ApiError(f"'{key}' is required")
        return None
    if not isinstance(v, str):
        raise ApiError(f"'{key}' must be a string")
    v = v.strip()
    if len(v) < min_len or len(v) > max_len:
        raise ApiError(f"'{key}' must be {min_len}-{max_len} characters")
    return v


def number(d, key, minimum=0.0, maximum=1e9, integer=False, required=True):
    v = d.get(key)
    if v is None:
        if required:
            raise ApiError(f"'{key}' is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(f"'{key}' must be a number")
    if integer and int(v) != v:
        raise ApiError(f"'{key}' must be a whole number")
    if v <= minimum or v > maximum:
        raise ApiError(f"'{key}' must be greater than {minimum} and at most {maximum}")
    return int(v) if integer else float(v)


def skills_str(v):
    if v is None:
        return ""
    items = v if isinstance(v, list) else str(v).split(",")
    clean = [str(s).strip() for s in items if str(s).strip()]
    if len(clean) > 20 or any(len(s) > 30 for s in clean):
        raise ApiError("Up to 20 skills of at most 30 characters each")
    return ",".join(clean)


def parse_date(v, key="deadline"):
    try:
        d = date.fromisoformat(str(v))
    except ValueError:
        raise ApiError(f"'{key}' must be an ISO date (YYYY-MM-DD)")
    return d


def create_token(user):
    exp = datetime.now(timezone.utc) + timedelta(minutes=current_app.config["JWT_EXPIRES_MINUTES"])
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, current_app.config["SECRET_KEY"], algorithm="HS256")


def auth_required(*roles):
    """Authentication + optional role check middleware."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return fail("Missing or malformed Authorization header", 401)
            try:
                payload = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"])
                user = db.session.get(User, int(payload["sub"]))
            except jwt.ExpiredSignatureError:
                return fail("Token has expired", 401)
            except (jwt.InvalidTokenError, ValueError):
                return fail("Invalid token", 401)
            if not user:
                return fail("User no longer exists", 401)
            if roles and user.role not in roles:
                return fail("Access denied for role '%s'. Required: %s" % (user.role, " or ".join(roles)), 403)
            g.user = user
            return fn(*a, **kw)
        return wrapper
    return deco




def rate_limit():
    limit = current_app.config["RATE_LIMIT_PER_MINUTE"]
    hits = current_app.extensions.setdefault("rate_hits", defaultdict(deque))
    q, t = hits[request.remote_addr], time.time()
    while q and q[0] < t - 60:
        q.popleft()
    if len(q) >= limit:
        return fail("Too many requests, slow down", 429)
    q.append(t)
