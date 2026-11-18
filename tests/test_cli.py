"""The ``prosit-tool`` launcher: options, port selection, single instance."""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from waitress import create_server

from prosit_tool import __version__, cli
from prosit_tool.cli import (
    LauncherError,
    build_parser,
    choose_port,
    main,
    public_url,
    running_instance,
    something_listens,
)
from prosit_tool.config import APP_NAME

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def live_prosit(app):
    """Serve ``app`` with the production server on an ephemeral port."""
    server = create_server(app, host=HOST, port=0, threads=2)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        yield server.effective_port
    finally:
        server.close()
        thread.join(timeout=5)


@contextlib.contextmanager
def other_program():
    """A TCP server that is not ProSiT: it accepts connections and hangs up."""
    sock = socket.socket()
    sock.bind((HOST, 0))
    sock.listen()
    sock.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                connection, _ = sock.accept()
            except OSError:  # accept timed out
                continue
            connection.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield sock.getsockname()[1]
    finally:
        stop.set()
        thread.join(timeout=2)
        sock.close()


# --- options ---------------------------------------------------------------------

def test_defaults_listen_on_this_computer_only():
    args = build_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port is None
    assert args.data_dir is None
    assert args.no_browser is False


def test_options_from_the_environment(monkeypatch):
    monkeypatch.setenv("PROSIT_TOOL_HOST", "0.0.0.0")
    monkeypatch.setenv("PROSIT_TOOL_NO_BROWSER", "1")

    args = build_parser().parse_args([])

    assert args.host == "0.0.0.0"
    assert args.no_browser is True
    # The command line still wins.
    assert build_parser().parse_args(["--host", "127.0.0.1"]).host == "127.0.0.1"


def test_version_option(capsys):
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"{APP_NAME} {__version__}"


@pytest.mark.parametrize("host, port, expected", [
    ("127.0.0.1", 5050, "http://localhost:5050"),
    ("localhost", 5050, "http://localhost:5050"),
    ("0.0.0.0", 8080, "http://localhost:8080"),
    ("::1", 5050, "http://localhost:5050"),
    ("192.168.1.20", 5050, "http://192.168.1.20:5050"),
    ("fe80::1", 5050, "http://[fe80::1]:5050"),
])
def test_public_url(host, port, expected):
    assert public_url(host, port) == expected


# --- port selection --------------------------------------------------------------

def test_something_listens():
    with other_program() as port:
        assert something_listens(HOST, port) is True
        # A server bound to every interface is reached through loopback.
        assert something_listens("0.0.0.0", port) is True
    assert something_listens(HOST, port) is False


def test_running_instance_recognises_prosit(app):
    with live_prosit(app) as port:
        assert running_instance(HOST, port) == {"app": APP_NAME, "status": "ok", "version": __version__}


def test_running_instance_ignores_other_programs():
    with other_program() as port:
        assert running_instance(HOST, port) is None
    assert running_instance(HOST, free_port()) is None


def test_free_port_is_used_as_requested():
    port = free_port()
    assert choose_port(HOST, port, explicit=False) == (port, None)
    assert choose_port(HOST, port, explicit=True) == (port, None)


def test_port_served_by_prosit_is_reported_as_running_instance(app):
    with live_prosit(app) as port:
        chosen, instance = choose_port(HOST, port, explicit=True)

    assert chosen == port
    assert instance["app"] == APP_NAME


def test_requested_port_taken_by_another_program_is_an_error():
    with other_program() as port:
        with pytest.raises(LauncherError, match="already used by another program"):
            choose_port(HOST, port, explicit=True)


def test_default_port_taken_by_another_program_moves_to_the_next_free_one():
    with other_program() as port:
        chosen, instance = choose_port(HOST, port, explicit=False)

        assert instance is None
        assert port < chosen <= port + cli.PORT_SEARCH_SPAN
        assert something_listens(HOST, chosen) is False


# --- main ------------------------------------------------------------------------

def test_main_opens_the_running_instance_instead_of_starting_another(app, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)

    with live_prosit(app) as port:
        assert main(["--port", str(port)]) == 0
        assert main(["--port", str(port), "--no-browser"]) == 0

    assert opened == [f"http://localhost:{port}"]
    out = capsys.readouterr().out
    assert out.count(f"ProSiT {__version__} is already running at http://localhost:{port}") == 2


def test_main_reports_a_port_used_by_another_program(capsys):
    with other_program() as port:
        assert main(["--port", str(port), "--no-browser"]) == 2

    err = capsys.readouterr().err
    assert err.startswith(f"{APP_NAME}: Port {port} is already used by another program")


def test_port_from_the_environment_counts_as_requested(monkeypatch, capsys):
    with other_program() as port:
        monkeypatch.setenv("FLASK_PORT", str(port))  # the pre-1.1 variable name
        assert main(["--no-browser"]) == 2
        monkeypatch.setenv("PROSIT_TOOL_PORT", str(port))
        assert main(["--no-browser"]) == 2

    assert capsys.readouterr().err.count("already used by another program") == 2


@pytest.mark.parametrize("argv, env, message", [
    (["--no-browser"], {"PROSIT_TOOL_PORT": "http"}, "PROSIT_TOOL_PORT must be a port number"),
    (["--no-browser", "--port", "0"], {}, "0 is not a valid port number"),
    (["--no-browser", "--port", "70000"], {}, "70000 is not a valid port number"),
])
def test_invalid_port_is_rejected(argv, env, message, monkeypatch, capsys):
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    assert main(argv) == 2
    assert message in capsys.readouterr().err


def test_launcher_serves_the_application(tmp_path):
    """Start the real command, as a user would, and talk to it over HTTP."""
    port = free_port()
    data_dir = tmp_path / "data"
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen(
        [sys.executable, "-m", "prosit_tool", "--port", str(port), "--no-browser", "--data-dir", str(data_dir)],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.monotonic() + 120
        while running_instance(HOST, port, timeout=1) is None:
            if process.poll() is not None:
                pytest.fail(f"launcher exited with {process.returncode}:\n{process.stdout.read()}")
            if time.monotonic() > deadline:
                pytest.fail("the server did not answer within two minutes")
            time.sleep(0.3)

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://{HOST}:{port}/", timeout=20) as response:
            assert response.status == 200
            assert b"ProSiT" in response.read()
        assert (data_dir / "instance" / "prosit.db").is_file()
        # The working directory is left alone: everything goes to the data dir.
        assert sorted(p.name for p in tmp_path.iterdir()) == ["data"]
    finally:
        if os.name == "posix":
            process.send_signal(signal.SIGINT)  # what Ctrl+C sends
        else:
            process.terminate()
        try:
            output, _ = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()

    assert f"ProSiT {__version__} is running at http://localhost:{port}" in output
    assert f"Data directory: {data_dir.resolve()}" in output
    if os.name == "posix":
        assert process.returncode == 0, output
