"""The application factory: data directory, database location, secret key."""

import io
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from prosit_tool import __version__
from prosit_tool.app import create_app
from prosit_tool.config import (
    APP_NAME,
    default_data_dir,
    resolve_data_paths,
    resolve_database_url,
    resolve_secret_key,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- data directory ----------------------------------------------------------

def test_data_directory_layout(tmp_path):
    app = create_app(tmp_path / "d", testing=True)
    root = (tmp_path / "d").resolve()

    assert app.config["DATA_DIR"] == str(root)
    assert app.config["UPLOAD_FOLDER"] == str(root / "uploads")
    assert app.config["SIMULATION_FOLDER"] == str(root / "simulations")
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///" + (root / "instance" / "prosit.db").as_posix()
    for sub in ("uploads", "simulations", "instance"):
        assert (root / sub).is_dir()
    assert (root / "instance" / "prosit.db").is_file()


def test_paths_are_absolute_even_for_a_relative_data_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app("relative-data", testing=True)

    for key in ("DATA_DIR", "UPLOAD_FOLDER", "SIMULATION_FOLDER"):
        assert os.path.isabs(app.config[key]), key
    assert app.config["DATA_DIR"] == str((tmp_path / "relative-data").resolve())


def test_data_dir_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSIT_TOOL_DATA_DIR", str(tmp_path / "from-env"))

    assert default_data_dir() == tmp_path / "from-env"
    assert resolve_data_paths().root == (tmp_path / "from-env").resolve()
    # An explicit directory wins over the environment.
    assert resolve_data_paths(tmp_path / "explicit").root == (tmp_path / "explicit").resolve()


def test_default_data_dir_is_per_user_not_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = default_data_dir()

    assert directory.is_absolute()
    assert directory.name == APP_NAME
    assert directory != tmp_path and tmp_path not in directory.parents


def test_two_applications_do_not_share_data(tmp_path, tiny_xes_path):
    first = create_app(tmp_path / "first", testing=True)
    second = create_app(tmp_path / "second", testing=True)

    with open(tiny_xes_path, "rb") as f:
        data = {"xes_file": (io.BytesIO(f.read()), tiny_xes_path.name)}
    resp = first.test_client().post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.data
    session_id = resp.get_json()["session_id"]

    assert len(os.listdir(first.config["UPLOAD_FOLDER"])) == 1
    assert os.listdir(second.config["UPLOAD_FOLDER"]) == []
    assert second.test_client().get(f"/api/sessions/{session_id}/runs").status_code == 404


def test_downloads_do_not_depend_on_the_working_directory(client, tiny_xes_path, tmp_path, monkeypatch):
    with open(tiny_xes_path, "rb") as f:
        data = {"xes_file": (io.BytesIO(f.read()), tiny_xes_path.name)}
    sid = client.post("/api/upload", data=data, content_type="multipart/form-data").get_json()["session_id"]
    assert client.post(f"/api/discover/{sid}").status_code == 200
    filename = client.post(f"/api/simulate/{sid}", json={"num_instances": 3}).get_json()["sim_output_filename"]

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert client.get(f"/api/download/{filename}").status_code == 200
    assert client.get(f"/api/download_xes/{filename}").status_code == 200
    assert client.get(f"/api/get_visualization/{sid}/case_duration_dist").status_code == 200
    assert list(elsewhere.iterdir()) == []


def test_importing_the_package_has_no_side_effects(tmp_path):
    """Importing must not create directories, databases or key files."""
    data_dir = tmp_path / "must-not-be-created"
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PROSIT_TOOL_DATA_DIR": str(data_dir),
    }
    env.pop("SESSION_SECRET", None)
    result = subprocess.run(
        [sys.executable, "-c", "import prosit_tool.app, prosit_tool.api, prosit_tool.cli"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert not data_dir.exists()
    assert list(tmp_path.iterdir()) == []


# --- database ------------------------------------------------------------------

def test_database_url_precedence(tmp_path, monkeypatch):
    paths = resolve_data_paths(tmp_path)
    assert resolve_database_url(paths) == "sqlite:///" + paths.database.as_posix()

    monkeypatch.setenv("DATABASE_URL", "sqlite:///from-env.db")
    assert resolve_database_url(paths) == "sqlite:///from-env.db"
    assert resolve_database_url(paths, "sqlite:///explicit.db") == "sqlite:///explicit.db"


def test_relative_sqlite_url_lands_in_the_data_dir(tmp_path, monkeypatch):
    """docker-compose.yml exports DATABASE_URL=sqlite:///prosit.db."""
    monkeypatch.chdir(tmp_path)  # a wrongly resolved file would show up here
    monkeypatch.setenv("DATABASE_URL", "sqlite:///prosit.db")

    create_app(tmp_path / "d", testing=True)

    assert (tmp_path / "d" / "instance" / "prosit.db").is_file()
    assert not (tmp_path / "prosit.db").exists()


# --- secret key ----------------------------------------------------------------

def test_application_starts_without_any_configuration(tmp_path):
    """No SESSION_SECRET and no FLASK_ENV used to make the tool refuse to start."""
    app = create_app(tmp_path, testing=True)

    assert app.secret_key
    assert app.test_client().get("/").status_code == 200


def test_secret_key_is_generated_once_and_reused(tmp_path):
    paths = resolve_data_paths(tmp_path / "a").create()

    first = resolve_secret_key(paths)
    assert len(first) >= 32
    assert paths.secret_key_file.read_text(encoding="utf-8") == first
    assert resolve_secret_key(paths) == first
    assert create_app(tmp_path / "a", testing=True).secret_key == first

    other = resolve_secret_key(resolve_data_paths(tmp_path / "b").create())
    assert other != first


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions")
def test_secret_key_file_is_private(tmp_path):
    paths = resolve_data_paths(tmp_path).create()
    resolve_secret_key(paths)

    assert stat.S_IMODE(paths.secret_key_file.stat().st_mode) == 0o600


def test_session_secret_from_the_environment_wins_and_is_not_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "from-the-environment")
    paths = resolve_data_paths(tmp_path).create()

    assert resolve_secret_key(paths) == "from-the-environment"
    assert not paths.secret_key_file.exists()


def test_empty_secret_key_file_is_replaced(tmp_path):
    paths = resolve_data_paths(tmp_path).create()
    paths.secret_key_file.write_text("  \n", encoding="utf-8")

    key = resolve_secret_key(paths)

    assert len(key) >= 32
    assert paths.secret_key_file.read_text(encoding="utf-8") == key


# --- health --------------------------------------------------------------------

def test_health_endpoint_identifies_the_application(client):
    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.get_json() == {"app": APP_NAME, "status": "ok", "version": __version__}
