from datetime import datetime, timezone

import bcrypt
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # client | freelancer
    profile_image = db.Column(db.String(255))
    bio = db.Column(db.Text)
    skills = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=now)

    def set_password(self, pw):
        self.password = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

    def check_password(self, pw):
        return bcrypt.checkpw(pw.encode(), self.password.encode())

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role, "profile_image": self.profile_image,
                "bio": self.bio, "skills": [s for s in (self.skills or "").split(",") if s], "created_at": self.created_at.isoformat()}


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    freelancer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(60), nullable=False, index=True)
    budget = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.String(255), default="")
    deadline = db.Column(db.Date, nullable=False)
    experience_level = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)  # open|in_progress|completed|cancelled
    created_at = db.Column(db.DateTime, default=now)
    proposals = db.relationship("Proposal", backref="project", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "client_id": self.client_id, "freelancer_id": self.freelancer_id, "title": self.title, "category": self.category,
                "budget": self.budget, "description": self.description, "required_skills": [s for s in (self.required_skills or "").split(",") if s],
                "deadline": self.deadline.isoformat(), "experience_level": self.experience_level, "status": self.status, "created_at": self.created_at.isoformat()}


class Proposal(db.Model):
    __tablename__ = "proposals"
    __table_args__ = (db.UniqueConstraint("project_id", "freelancer_id", name="uq_one_bid_per_project"),)
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    freelancer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    bid_amount = db.Column(db.Float, nullable=False)
    cover_letter = db.Column(db.Text, nullable=False)
    delivery_time = db.Column(db.Integer, nullable=False)  # days
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending|accepted|rejected
    submitted_at = db.Column(db.DateTime, default=now)
    freelancer = db.relationship("User", foreign_keys=[freelancer_id])

    def to_dict(self):
        return {"id": self.id, "project_id": self.project_id, "freelancer_id": self.freelancer_id, "freelancer_name": self.freelancer.name,
                "bid_amount": self.bid_amount, "cover_letter": self.cover_letter, "delivery_time": self.delivery_time,
                "status": self.status, "submitted_at": self.submitted_at.isoformat()}


class Contract(db.Model):
    __tablename__ = "contracts"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), unique=True, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    freelancer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    contract_status = db.Column(db.String(20), nullable=False, default="pending")  # pending|active|completed|cancelled
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {"id": self.id, "project_id": self.project_id, "client_id": self.client_id, "freelancer_id": self.freelancer_id,
                "contract_status": self.contract_status, "started_at": self.started_at and self.started_at.isoformat(),
                "completed_at": self.completed_at and self.completed_at.isoformat()}
