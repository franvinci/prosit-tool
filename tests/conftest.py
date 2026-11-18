"""Shared pytest fixtures for the prosit-tool suite.

Every test gets its own application, built by the factory on a temporary data
directory: its own SQLite file, upload folder and simulation folder. Nothing is
read from, or written to, the real data or the environment of whoever runs the
tests.
"""

import io
import os
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


@pytest.fixture
def upload(client):
    """``upload(xes_path, pnml_path=None, **form_fields)`` -> the HTTP response."""
    def _upload(log_path, pnml_path=None, **form):
        data = dict(form)
        with open(log_path, "rb") as handle:
            data["xes_file"] = (io.BytesIO(handle.read()), Path(log_path).name)
        if pnml_path is not None:
            with open(pnml_path, "rb") as handle:
                data["pnml_file"] = (io.BytesIO(handle.read()), Path(pnml_path).name)
        return client.post("/api/upload", data=data, content_type="multipart/form-data")
    return _upload


@pytest.fixture
def discovered(client, upload):
    """``discovered(xes_path, query="", pnml_path=None)`` -> ``(session_id, discovery body)``."""
    def _discovered(log_path, query="", pnml_path=None, **form):
        response = upload(log_path, pnml_path, **form)
        assert response.status_code == 200, response.data
        session_id = response.get_json()["session_id"]
        response = client.post(f"/api/discover/{session_id}{query}")
        assert response.status_code == 200, response.data
        return session_id, response.get_json()
    return _discovered


@pytest.fixture
def data_files(app):
    """``data_files()`` -> ``(names in the upload folder, names in the simulation folder)``."""
    def _data_files():
        return (
            sorted(os.listdir(app.config["UPLOAD_FOLDER"])),
            sorted(os.listdir(app.config["SIMULATION_FOLDER"])),
        )
    return _data_files


def write_xes(rows, path):
    """Write event rows (dicts with pm4py column names) as an XES file."""
    import pandas as pd
    import pm4py

    pm4py.write_xes(pm4py.convert_to_event_log(pd.DataFrame(rows)), str(path))
    return path


def event_rows(activities=("A", "B", "C", "D"), cases=5, resources=("r1", "r1", "r2", "r2"),
               with_start=True, minutes=10):
    """Rows of a small sequential log: every case runs ``activities`` in order."""
    import pandas as pd

    rows = []
    base = pd.Timestamp("2024-01-01 08:00", tz="UTC")
    for case in range(cases):
        for position, activity in enumerate(activities):
            start = base + pd.Timedelta(hours=case * 2 + position * 0.5)
            row = {
                "case:concept:name": f"c{case}",
                "concept:name": activity,
                "time:timestamp": start + pd.Timedelta(minutes=minutes),
            }
            if with_start:
                row["start:timestamp"] = start
            if resources is not None:
                row["org:resource"] = resources[position % len(resources)]
            rows.append(row)
    return rows


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
