"""Flask blueprint package for the prosit-tool HTTP API.

Each module exposes a Blueprint at module-level. ``register_blueprints``
attaches them all to the Flask app at startup; this is the function that
``app.py`` imports to wire everything up.
"""

from flask import render_template

from . import discovery, errors, parameters, runs, simulation, upload, visualization


def register_blueprints(app):
    """Register every blueprint and a few app-level routes/handlers."""
    app.register_blueprint(upload.bp)
    app.register_blueprint(discovery.bp)
    app.register_blueprint(parameters.bp)
    app.register_blueprint(runs.bp)
    app.register_blueprint(simulation.bp)
    app.register_blueprint(visualization.bp)

    errors.register(app)

    @app.route('/')
    def index():
        from models import SimulationSession  # local import to avoid circular load
        sessions = (
            SimulationSession.query
            .order_by(
                SimulationSession.last_used_at.desc().nullslast(),
                SimulationSession.created_at.desc(),
            )
            .limit(15)
            .all()
        )
        # Hydrate each session with the data the template needs without
        # touching its model definition: a clean label, run summary, and the
        # filename of the most recent simulation (if any) so the badge can
        # reflect "completed" vs "ready" accurately.
        for s in sessions:
            s._display_label = s.display_label()
            s._run_count = len(s.runs) if s.runs else 0
            s._has_simulation = any(r.simulation_df_filename for r in s.runs)
        return render_template('index.html', sessions=sessions)
