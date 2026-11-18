"""Flask application factory."""

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config, resolve_data_paths, resolve_database_url, resolve_secret_key
from .extensions import db


def create_app(data_dir=None, *, database_url=None, testing=False) -> Flask:
    """Build a ProSiT application whose files live under ``data_dir``.

    Args:
        data_dir: Directory for uploads, simulation logs and the database.
            Defaults to ``$PROSIT_TOOL_DATA_DIR`` or the per-user data
            directory (see :func:`prosit_tool.config.default_data_dir`).
        database_url: SQLAlchemy URL overriding ``$DATABASE_URL`` and the
            SQLite file inside ``data_dir``.
        testing: Sets Flask's ``TESTING`` flag.
    """
    paths = resolve_data_paths(data_dir).create()

    # instance_path keeps a relative SQLite URL (``sqlite:///prosit.db``)
    # pointing inside the data directory rather than next to the installed code.
    app = Flask(__name__, instance_path=str(paths.instance))
    app.config.update(
        TESTING=testing,
        DATA_DIR=str(paths.root),
        UPLOAD_FOLDER=str(paths.uploads),
        SIMULATION_FOLDER=str(paths.simulations),
        MAX_CONTENT_LENGTH=Config.MAX_UPLOAD_SIZE,
        SQLALCHEMY_DATABASE_URI=resolve_database_url(paths, database_url),
        SQLALCHEMY_ENGINE_OPTIONS={
            'pool_recycle': Config.POOL_RECYCLE,
            'pool_pre_ping': True,
        },
    )
    app.secret_key = resolve_secret_key(paths)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    db.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401  (registers the tables on ``db``)
        db.create_all()

    from .api import register_blueprints
    register_blueprints(app)

    return app
