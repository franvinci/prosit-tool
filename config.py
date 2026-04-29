"""Centralized constants and Flask configuration for prosit-tool.

Until this module landed, defaults were sprinkled across ``app.py``,
``main.py``, ``models.py``, and the API endpoints. They now live in one place
so a single edit changes the value everywhere it matters.
"""

import os


class Config:
    # --- Discovery defaults --------------------------------------------------
    DEFAULT_NOISE_THRESHOLD = 0.2
    MAX_NOISE_THRESHOLD = 1.0

    DEFAULT_MAX_DEPTH_TREE = 0
    MAX_DEPTH_TREE = 5

    DEFAULT_GRACE_PERIOD = 1000
    MIN_GRACE_PERIOD = 1

    # New in prosit-pm 1.0.2.
    DEFAULT_MULTITASKING_THR = 0.05
    DEFAULT_RANDOM_STATE = 72
    DEFAULT_ATTRIBUTE_MODE = 'distribution'

    # --- Simulation defaults --------------------------------------------------
    MIN_INSTANCES = 1
    MAX_INSTANCES = 10_000
    DEFAULT_INSTANCES = 100

    # --- Web/server settings --------------------------------------------------
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
    PORT = int(os.environ.get('FLASK_PORT', 5050))
    POOL_RECYCLE = 300

    UPLOAD_FOLDER = 'uploads'
    SIMULATION_FOLDER = 'simulations'

    ALLOWED_UPLOAD_EXTENSIONS = ('xes', 'pnml')

    # --- Database -------------------------------------------------------------
    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///prosit.db')


def apply_to_flask(app):
    """Populate ``app.config`` from the constants above and the environment."""
    app.config['MAX_CONTENT_LENGTH'] = Config.MAX_UPLOAD_SIZE
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
    app.config['SIMULATION_FOLDER'] = Config.SIMULATION_FOLDER

    app.config['SQLALCHEMY_DATABASE_URI'] = Config.DATABASE_URL
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': Config.POOL_RECYCLE,
        'pool_pre_ping': True,
    }

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.SIMULATION_FOLDER, exist_ok=True)
