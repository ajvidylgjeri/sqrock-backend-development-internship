import logging
import warnings

from flask import Flask
from flask_cors import CORS

from .config import Config
from .models import Coin, User, db
from .utils import ApiError, fail, rate_limit

warnings.filterwarnings("ignore", message="Dialect sqlite\\+pysqlite does \\*not\\* support Decimal")

SEED_COINS = [("Bitcoin", "BTC", "65000"), ("Ethereum", "ETH", "3200"), ("Solana", "SOL", "150"), ("Binance Coin", "BNB", "580"), ("Tether", "USDT", "1")]


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
    def unexpected(e):
        logging.exception("Unhandled error")
        return fail("Internal server error", 500)

    with app.app_context():
        db.create_all()
        if not Coin.query.count():
            for name, sym, price in SEED_COINS:
                db.session.add(Coin(coin_name=name, coin_symbol=sym, current_price=price))
            db.session.commit()
        email, pw = app.config.get("ADMIN_EMAIL"), app.config.get("ADMIN_PASSWORD")
        if email and pw and not User.query.filter_by(email=email.lower()).first():
            a = User(name="Administrator", email=email.lower(), role="admin", email_verified=True)
            a.set_password(pw)
            db.session.add(a)
            db.session.commit()
    return app
