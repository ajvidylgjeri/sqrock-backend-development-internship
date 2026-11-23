import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-change-me-0123456789abcdef")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///exchange.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_EXPIRES_MINUTES = int(os.environ.get("JWT_EXPIRES_MINUTES", "60"))
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
    AUTH_RATE_LIMIT_PER_MINUTE = int(os.environ.get("AUTH_RATE_LIMIT_PER_MINUTE", "10"))
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    RATE_LIMIT_PER_MINUTE = 100000
    AUTH_RATE_LIMIT_PER_MINUTE = 100000
    ADMIN_EMAIL = None
    ADMIN_PASSWORD = None
