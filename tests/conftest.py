"""Shared pytest fixtures for the prosit-tool smoke suite.

Spins up the real Flask app pointed at tmp directories and an isolated
SQLite database. Each test gets a fresh database and clean upload/sim
folders so they cannot interfere with each other.
"""

import os
import sys
from pathlib import Path

# Set env vars BEFORE importing app — app.py reads them at module load.
os.environ.setdefault("SESSION_SECRET", "test-secret-dont-use-in-prod")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# Make the project root importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from app import app as flask_app, db


PURCHASING_XES = PROJECT_ROOT / "example_data" / "purchasing.xes"


@pytest.fixture
def client(tmp_path):
    """Flask test client backed by a fresh tmp database and folders."""
    uploads = tmp_path / "uploads"
    sims = tmp_path / "simulations"
    uploads.mkdir()
    sims.mkdir()

    flask_app.config["UPLOAD_FOLDER"] = str(uploads)
    flask_app.config["SIMULATION_FOLDER"] = str(sims)
    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        with flask_app.test_client() as c:
            yield c
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="session")
def small_xes_path():
    """Path to a small XES file from example_data."""
    assert PURCHASING_XES.exists(), f"Missing test fixture: {PURCHASING_XES}"
    return PURCHASING_XES


@pytest.fixture(scope="session")
def small_pnml_path(tmp_path_factory, small_xes_path):
    """Discover a Petri net from the small XES and write it as PNML."""
    import pm4py
    from pm4py.objects.log.importer.xes import importer as xes_importer

    out = tmp_path_factory.mktemp("pnml") / "purchasing.pnml"
    log = xes_importer.apply(str(small_xes_path))
    net, im, fm = pm4py.discover_petri_net_inductive(log, noise_threshold=0.2)
    pm4py.write_pnml(net, im, fm, str(out))
    return out
