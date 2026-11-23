import logging

from flask import Flask
from flask_cors import CORS

from .config import Config
from .models import db
from .utils import ApiError, fail, rate_limit


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)
    db.init_app(app)
    CORS(app, origins=app.config["CORS_ORIGINS"])

    from .routes import bp
    app.register_blueprint(bp)
    app.before_request(rate_limit)

    @app.errorhandler(ApiError)
    def api_error(e):
        return fail(e.message, e.status)

    @app.errorhandler(404)
    def nf(_):
        return fail("Resource not found", 404)

    @app.errorhandler(405)
    def na(_):
        return fail("Method not allowed", 405)

    @app.errorhandler(Exception)
    def unexpected(e):  # never leak internals to the client
        logging.exception("Unhandled error")
        return fail("Internal server error", 500)

    with app.app_context():
        db.create_all()
    return app
