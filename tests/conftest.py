"""Shared pytest fixtures for the prosit-tool suite.

Every test gets its own application, built by the factory on a temporary data
directory: its own SQLite file, upload folder and simulation folder. Nothing is
read from, or written to, the real data or the environment of whoever runs the
tests.
"""

import sys
from pathlib import Path

# Make the checkout importable without installing it.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from prosit_tool.app import create_app
from prosit_tool.extensions import db


PURCHASING_XES = PROJECT_ROOT / "example_data" / "purchasing.xes"

# Settings a developer may have exported for their own instance. A test must
# never pick them up: DATABASE_URL in particular would point the suite at a
# real database.
_AMBIENT_SETTINGS = (
    "DATABASE_URL",
    "SESSION_SECRET",
    "PROSIT_TOOL_DATA_DIR",
    "PROSIT_TOOL_HOST",
    "PROSIT_TOOL_PORT",
    "PROSIT_TOOL_NO_BROWSER",
    "FLASK_PORT",
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch):
    for name in _AMBIENT_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def app(tmp_path):
    """A fresh application whose data directory is ``tmp_path/data``."""
    application = create_app(tmp_path / "data", testing=True)
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    """Flask test client; an application context stays active for the test."""
    with app.app_context():
        with app.test_client() as c:
            yield c


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


@pytest.fixture(scope="session")
def tiny_xes_path(tmp_path_factory):
    """Synthetic XES with a handful of traces — used by tests that exercise the
    full simulate+evaluate pipeline without paying the cost of a real log."""
    import pandas as pd
    import pm4py

    rows = []
    base = pd.Timestamp("2024-01-01 08:00", tz="UTC")
    for case in range(5):
        for ev, (act, res) in enumerate([
            ("A", "r1"), ("B", "r1"), ("C", "r2"), ("D", "r2"),
        ]):
            start = base + pd.Timedelta(hours=case * 2 + ev * 0.5)
            end = start + pd.Timedelta(minutes=10)
            rows.append({
                "case:concept:name": f"c{case}",
                "concept:name": act,
                "org:resource": res,
                "start:timestamp": start,
                "time:timestamp": end,
            })
    df = pd.DataFrame(rows)
    out = tmp_path_factory.mktemp("xes") / "tiny.xes"
    log = pm4py.convert_to_event_log(df)
    pm4py.write_xes(log, str(out))
    return out
