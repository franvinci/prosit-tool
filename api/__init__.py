"""Flask blueprint package for the prosit-tool HTTP API.

Each module exposes a Blueprint at module-level. ``register_blueprints``
attaches them all to the Flask app at startup; this is the function that
``app.py`` imports to wire everything up.
"""

from flask import render_template

from . import discovery, errors, parameters, simulation, upload, visualization


def register_blueprints(app):
    """Register every blueprint and a few app-level routes/handlers."""
    app.register_blueprint(upload.bp)
    app.register_blueprint(discovery.bp)
    app.register_blueprint(parameters.bp)
    app.register_blueprint(simulation.bp)
    app.register_blueprint(visualization.bp)

    errors.register(app)

    @app.route('/')
    def index():
        from models import SimulationSession  # local import to avoid circular load
        sessions = (
            SimulationSession.query
            .order_by(SimulationSession.created_at.desc())
            .limit(10)
            .all()
        )
        return render_template('index.html', sessions=sessions)
