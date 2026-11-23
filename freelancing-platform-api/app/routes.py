from datetime import date

from flask import Blueprint, g, request
from sqlalchemy import func, or_

from .models import Contract, Project, Proposal, User, db, now
from .utils import (ApiError, auth_required, body, create_token, EMAIL_RE, number, ok, parse_date, skills_str, text)

bp = Blueprint("api", __name__)
LEVELS = {"beginner", "intermediate", "expert"}
ROLES = {"client", "freelancer"}


@bp.get("/health")
def health():
    return ok({"status": "ok"})


# ---------------- auth ----------------
@bp.post("/signup")
def signup():
    d = body()
    name, email = text(d, "name", 2, 100), (text(d, "email", 5, 120) or "").lower()
    pw, role = d.get("password"), d.get("role")
    if not EMAIL_RE.match(email):
        raise ApiError("Enter a valid email address")
    if not isinstance(pw, str) or len(pw) < 8 or len(pw) > 72:
        raise ApiError("Password must be 8-72 characters")
    if role not in ROLES:
        raise ApiError("'role' must be 'client' or 'freelancer'")
    if User.query.filter_by(email=email).first():
        raise ApiError("Email already registered", 409)
    u = User(name=name, email=email, role=role, bio=text(d, "bio", 1, 1000, required=False), skills=skills_str(d.get("skills")),
             profile_image=text(d, "profile_image", 1, 255, required=False))
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()
    return ok({"user": u.to_dict(), "token": create_token(u)}, 201)


@bp.post("/login")
def login():
    d = body()
    u = User.query.filter_by(email=str(d.get("email", "")).strip().lower()).first()
    if not u or not isinstance(d.get("password"), str) or not u.check_password(d["password"]):
        raise ApiError("Invalid email or password", 401)
    return ok({"user": u.to_dict(), "token": create_token(u)})


# ---------------- projects ----------------
def project_fields(d, partial=False):
    out = {}
    req = not partial

    def want(k):
        return req or k in d
    if want("title"):
        out["title"] = text(d, "title", 5, 150)
    if want("category"):
        out["category"] = text(d, "category", 2, 60).lower()
    if want("budget"):
        out["budget"] = number(d, "budget", 0, 10_000_000)
    if want("description"):
        out["description"] = text(d, "description", 20, 5000)
    if want("deadline"):
        dl = parse_date(d.get("deadline"))
        if dl <= date.today():
            raise ApiError("'deadline' must be in the future")
        out["deadline"] = dl
    if want("experience_level"):
        if d.get("experience_level") not in LEVELS:
            raise ApiError("'experience_level' must be one of: " + ", ".join(sorted(LEVELS)))
        out["experience_level"] = d["experience_level"]
    if "required_skills" in d or req:
        out["required_skills"] = skills_str(d.get("required_skills"))
    return out


def get_project(pid):
    p = db.session.get(Project, pid)
    if not p:
        raise ApiError("Project not found", 404)
    return p


def own_project(pid):
    p = get_project(pid)
    if p.client_id != g.user.id:
        raise ApiError("You do not own this project", 403)
    return p


@bp.post("/projects")
@auth_required("client")
def create_project():
    p = Project(client_id=g.user.id, **project_fields(body()))
    db.session.add(p)
    db.session.commit()
    return ok(p.to_dict(), 201)


@bp.get("/projects")
@auth_required()
def list_projects():
    q = Project.query
    if g.user.role == "client" and request.args.get("mine") in ("1", "true"):
        q = q.filter_by(client_id=g.user.id)
    status = request.args.get("status", "open")
    if status != "all":
        q = q.filter_by(status=status)
    if request.args.get("category"):
        q = q.filter(Project.category == request.args["category"].lower())
    if request.args.get("level"):
        q = q.filter(Project.experience_level == request.args["level"])
    s = request.args.get("search", "").strip()
    if s:
        like = f"%{s}%"
        q = q.filter(or_(Project.title.ilike(like), Project.description.ilike(like), Project.required_skills.ilike(like)))
    for key, op in (("min_budget", lambda c, v: c >= v), ("max_budget", lambda c, v: c <= v)):
        if request.args.get(key):
            try:
                q = q.filter(op(Project.budget, float(request.args[key])))
            except ValueError:
                raise ApiError(f"'{key}' must be a number")
    try:
        page, per = max(1, int(request.args.get("page", 1))), min(50, max(1, int(request.args.get("per_page", 10))))
    except ValueError:
        raise ApiError("'page' and 'per_page' must be integers")
    total = q.count()
    items = q.order_by(Project.created_at.desc(), Project.id.desc()).offset((page - 1) * per).limit(per).all()
    return ok([p.to_dict() for p in items], page=page, per_page=per, total=total)


@bp.get("/projects/<int:pid>")
@auth_required()
def project_detail(pid):
    p = get_project(pid)
    data = p.to_dict()
    data["proposal_count"] = len(p.proposals)
    return ok(data)


@bp.put("/projects/<int:pid>")
@auth_required("client")
def edit_project(pid):
    p = own_project(pid)
    if p.status != "open" or p.freelancer_id:
        raise ApiError("Only open, unassigned projects can be edited", 409)
    fields = project_fields(body(), partial=True)
    if not fields:
        raise ApiError("No editable fields supplied")
    for k, v in fields.items():
        setattr(p, k, v)
    db.session.commit()
    return ok(p.to_dict())


@bp.delete("/projects/<int:pid>")
@auth_required("client")
def delete_project(pid):
    p = own_project(pid)
    if p.status == "in_progress" or p.freelancer_id and p.status == "open":
        raise ApiError("Assigned or in-progress projects must be cancelled before deletion", 409)
    db.session.delete(p)
    db.session.commit()
    return ok({"deleted": pid})


# ---------------- proposals ----------------
def get_proposal(pid):
    pr = db.session.get(Proposal, pid)
    if not pr:
        raise ApiError("Proposal not found", 404)
    return pr


@bp.post("/projects/<int:pid>/proposal")
@auth_required("freelancer")
def submit_proposal(pid):
    p = get_project(pid)
    if p.status != "open" or p.freelancer_id:
        raise ApiError("This project is not accepting proposals", 409)
    if Proposal.query.filter_by(project_id=pid, freelancer_id=g.user.id).first():
        raise ApiError("You already submitted a proposal for this project", 409)
    d = body()
    pr = Proposal(project_id=pid, freelancer_id=g.user.id, bid_amount=number(d, "bid_amount", 0, 10_000_000),
                  cover_letter=text(d, "cover_letter", 20, 3000), delivery_time=number(d, "delivery_time", 0, 3650, integer=True))
    db.session.add(pr)
    db.session.commit()
    return ok(pr.to_dict(), 201)


@bp.get("/my-proposals")
@auth_required("freelancer")
def my_proposals():
    rows = Proposal.query.filter_by(freelancer_id=g.user.id).order_by(Proposal.submitted_at.desc(), Proposal.id.desc()).all()
    return ok([dict(r.to_dict(), project_title=r.project.title, project_status=r.project.status) for r in rows])


@bp.get("/projects/<int:pid>/proposals")
@auth_required("client")
def project_proposals(pid):
    p = own_project(pid)
    return ok([r.to_dict() for r in sorted(p.proposals, key=lambda r: r.submitted_at, reverse=True)])


@bp.put("/proposal/<int:prid>/accept")
@auth_required("client")
def accept_proposal(prid):
    pr = get_proposal(prid)
    p = own_project(pr.project_id)
    if p.status != "open" or p.freelancer_id:
        raise ApiError("This project already has an assigned freelancer or is closed", 409)
    if pr.status != "pending":
        raise ApiError(f"Proposal is already {pr.status}", 409)
    pr.status = "accepted"
    for other in p.proposals:
        if other.id != pr.id and other.status == "pending":
            other.status = "rejected"
    p.freelancer_id = pr.freelancer_id
    c = Contract(project_id=p.id, client_id=p.client_id, freelancer_id=pr.freelancer_id, contract_status="pending")
    db.session.add(c)
    db.session.commit()
    return ok({"proposal": pr.to_dict(), "project": p.to_dict(), "contract": c.to_dict()})


@bp.put("/proposal/<int:prid>/reject")
@auth_required("client")
def reject_proposal(prid):
    pr = get_proposal(prid)
    own_project(pr.project_id)
    if pr.status != "pending":
        raise ApiError(f"Proposal is already {pr.status}", 409)
    pr.status = "rejected"
    db.session.commit()
    return ok(pr.to_dict())


@bp.delete("/proposal/<int:prid>")
@auth_required("freelancer")
def withdraw_proposal(prid):
    pr = get_proposal(prid)
    if pr.freelancer_id != g.user.id:
        raise ApiError("This is not your proposal", 403)
    if pr.status != "pending":
        raise ApiError("Only pending proposals can be withdrawn", 409)
    db.session.delete(pr)
    db.session.commit()
    return ok({"withdrawn": prid})


# ---------------- project status ----------------
def contract_of(p):
    return Contract.query.filter_by(project_id=p.id).first()


@bp.put("/project/<int:pid>/start")
@auth_required("client")
def start_project(pid):
    p = own_project(pid)
    if p.status != "open" or not p.freelancer_id:
        raise ApiError("Accept a proposal first; only assigned open projects can be started", 409)
    p.status = "in_progress"
    c = contract_of(p)
    c.contract_status, c.started_at = "active", now()
    db.session.commit()
    return ok({"project": p.to_dict(), "contract": c.to_dict()})


@bp.put("/project/<int:pid>/complete")
@auth_required("client")
def complete_project(pid):
    p = own_project(pid)
    if p.status != "in_progress":
        raise ApiError("Only in-progress projects can be completed", 409)
    p.status = "completed"
    c = contract_of(p)
    c.contract_status, c.completed_at = "completed", now()
    db.session.commit()
    return ok({"project": p.to_dict(), "contract": c.to_dict()})


@bp.put("/project/<int:pid>/cancel")
@auth_required("client")
def cancel_project(pid):
    p = own_project(pid)
    if p.status not in ("open", "in_progress"):
        raise ApiError(f"A {p.status} project cannot be cancelled", 409)
    p.status = "cancelled"
    c = contract_of(p)
    if c:
        c.contract_status = "cancelled"
    for pr in p.proposals:
        if pr.status == "pending":
            pr.status = "rejected"
    db.session.commit()
    return ok(p.to_dict())


# ---------------- dashboards ----------------
@bp.get("/client/dashboard")
@auth_required("client")
def client_dashboard():
    ids = [r.id for r in Project.query.filter_by(client_id=g.user.id).all()]
    by = lambda s: Project.query.filter_by(client_id=g.user.id, status=s).count()
    return ok({"total_projects": len(ids), "active_projects": by("in_progress"), "open_projects": by("open"), "completed_projects": by("completed"),
               "cancelled_projects": by("cancelled"),
               "total_proposals_received": Proposal.query.filter(Proposal.project_id.in_(ids)).count() if ids else 0})


@bp.get("/freelancer/dashboard")
@auth_required("freelancer")
def freelancer_dashboard():
    fid = g.user.id
    assigned = lambda s: Project.query.filter_by(freelancer_id=fid, status=s).count()
    return ok({"applied_projects": Proposal.query.filter_by(freelancer_id=fid).count(), "active_projects": assigned("in_progress"),
               "completed_projects": assigned("completed"), "accepted_proposals": Proposal.query.filter_by(freelancer_id=fid, status="accepted").count(),
               "total_earnings": float(db.session.query(func.coalesce(func.sum(Proposal.bid_amount), 0.0)).join(Project, Project.id == Proposal.project_id)
                                       .filter(Proposal.freelancer_id == fid, Proposal.status == "accepted", Project.status == "completed").scalar())})
