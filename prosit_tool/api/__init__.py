"""Flask blueprint package for the prosit-tool HTTP API.

Each module exposes a Blueprint at module-level. ``register_blueprints``
attaches them all to an application; ``prosit_tool.app.create_app`` calls it.
"""

from flask import render_template

from . import discovery, errors, parameters, runs, simulation, system, upload, visualization


def register_blueprints(app):
    """Register every blueprint and a few app-level routes/handlers."""
    app.register_blueprint(system.bp)
    app.register_blueprint(upload.bp)
    app.register_blueprint(discovery.bp)
    app.register_blueprint(parameters.bp)
    app.register_blueprint(runs.bp)
    app.register_blueprint(simulation.bp)
    app.register_blueprint(visualization.bp)

    errors.register(app)

    @app.route('/')
    def index():
        # The page is the same for everybody: what it shows (sessions,
        # parameters, results) is loaded by its scripts through the API.
        return render_template('index.html')
