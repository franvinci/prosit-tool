import os
import logging
import secrets
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

from config import apply_to_flask

# Configure logging for the application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _resolve_secret_key():
    """Return SESSION_SECRET from env, or generate one in dev/testing modes.

    Refuses to start in production without an explicit secret.
    """
    secret = os.environ.get("SESSION_SECRET")
    if secret:
        return secret

    flask_env = os.environ.get("FLASK_ENV", "").lower()
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true")
    if flask_env in ("development", "testing") or debug:
        generated = secrets.token_hex(32)
        logger.warning(
            "SESSION_SECRET not set; generated an ephemeral key for dev/testing. "
            "Set SESSION_SECRET in production."
        )
        return generated

    raise RuntimeError(
        "SESSION_SECRET environment variable is required in production. "
        "Set FLASK_ENV=development or FLASK_DEBUG=1 to use an ephemeral key during dev."
    )


class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Initialize Flask application
app = Flask(__name__)
app.secret_key = _resolve_secret_key()
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

apply_to_flask(app)
db.init_app(app)

with app.app_context():
    # Import models and create database tables
    import models
    db.create_all()

# Wire up the HTTP API
from api import register_blueprints
register_blueprints(app)
