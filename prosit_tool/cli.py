"""Command-line launcher: ``prosit-tool`` and ``python -m prosit_tool``.

Starts the web server on this machine and opens it in the default browser.
Importing this module is cheap on purpose: the scientific stack is loaded only
once the launcher knows it actually has to start a server.
"""

import argparse
import json
import logging
import multiprocessing
import os
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__
from .config import APP_NAME, ENV_DATA_DIR, Config, default_data_dir

ENV_HOST = 'PROSIT_TOOL_HOST'
ENV_PORT = 'PROSIT_TOOL_PORT'
ENV_NO_BROWSER = 'PROSIT_TOOL_NO_BROWSER'
LEGACY_ENV_PORT = 'FLASK_PORT'  # the name the tool used up to 1.0

# How many ports above the default are tried when it is taken by another program.
PORT_SEARCH_SPAN = 20
SERVER_THREADS = 8
WILDCARD_HOSTS = ('0.0.0.0', '::', '')
LOOPBACK_HOSTS = ('127.0.0.1', '::1', 'localhost')


class LauncherError(Exception):
    """A start-up problem the user can fix; printed without a traceback."""


def _env_flag(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _env_port():
    """Port requested through the environment, or ``None``."""
    for name in (ENV_PORT, LEGACY_ENV_PORT):
        raw = os.environ.get(name, '').strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                raise LauncherError(f'{name} must be a port number, got {raw!r}') from None
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description='ProSiT: discover a simulation model from an event log, edit it, simulate it.',
    )
    parser.add_argument(
        '--host', default=os.environ.get(ENV_HOST) or Config.DEFAULT_HOST,
        help=f'address to listen on (default: {Config.DEFAULT_HOST}, this computer only; '
             f'use 0.0.0.0 to accept connections from the network). Env: {ENV_HOST}',
    )
    parser.add_argument(
        '--port', type=int, default=None,
        help=f'port to listen on (default: {Config.DEFAULT_PORT}, or the next free one). Env: {ENV_PORT}',
    )
    parser.add_argument(
        '--data-dir', type=Path, default=None,
        help=f'where uploads, simulations and the database are kept '
             f'(default: {default_data_dir()}). Env: {ENV_DATA_DIR}',
    )
    parser.add_argument(
        '--no-browser', action='store_true', default=_env_flag(ENV_NO_BROWSER),
        help=f'do not open the browser. Env: {ENV_NO_BROWSER}=1',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    return parser


def _probe_host(host: str) -> str:
    """The address through which this machine reaches a server bound to ``host``."""
    if host in WILDCARD_HOSTS:
        return '127.0.0.1'
    return host


def public_url(host: str, port: int) -> str:
    """URL to show to the user and to open in the browser."""
    if host in WILDCARD_HOSTS or host in LOOPBACK_HOSTS:
        return f'http://localhost:{port}'
    if ':' in host:  # IPv6 literal
        return f'http://[{host}]:{port}'
    return f'http://{host}:{port}'


def something_listens(host: str, port: int, timeout: float = 0.5) -> bool:
    """True if a TCP server already accepts connections on ``host:port``.

    Connecting is the only check that behaves the same everywhere: binding a
    second socket to a busy port succeeds on Windows when SO_REUSEADDR is set,
    which is what the web server does.
    """
    try:
        with socket.create_connection((_probe_host(host), port), timeout=timeout):
            return True
    except OSError:
        return False


def running_instance(host: str, port: int, timeout: float = 2.0):
    """The ``/api/health`` payload of a ProSiT listening on the port, or ``None``."""
    target = _probe_host(host)
    if ':' in target:
        target = f'[{target}]'
    url = f'http://{target}:{port}/api/health'
    # No proxies: an HTTP proxy configured in the environment must not be asked
    # to reach a server on this machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return None
    if isinstance(payload, dict) and payload.get('app') == APP_NAME:
        return payload
    return None


def choose_port(host: str, requested: int, explicit: bool):
    """Decide where to listen.

    Returns ``(port, instance)``. ``instance`` is the health payload of a ProSiT
    that already serves ``port`` (then there is nothing to start), else ``None``.
    A port taken by another program is an error when the user asked for that
    port, otherwise the next free one is used.
    """
    if not something_listens(host, requested):
        return requested, None

    instance = running_instance(host, requested)
    if instance is not None:
        return requested, instance

    if explicit:
        raise LauncherError(
            f'Port {requested} is already used by another program. '
            f'Choose a different one with --port.'
        )
    for candidate in range(requested + 1, requested + 1 + PORT_SEARCH_SPAN):
        if not something_listens(host, candidate):
            return candidate, None
    raise LauncherError(
        f'Ports {requested}-{requested + PORT_SEARCH_SPAN} are all in use. '
        f'Choose a free one with --port.'
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )


def _prepare_frozen_runtime() -> None:
    """Settings needed only when running as a PyInstaller executable."""
    if not getattr(sys, 'frozen', False):
        return
    # joblib's process workers are started with ``python -m ...``, which an
    # executable cannot do. One "CPU" makes prosit-pm fit its models in this
    # process, in the deterministic order it uses when no workers are available.
    os.environ.setdefault('LOKY_MAX_CPU_COUNT', '1')


def main(argv=None) -> int:
    # Must come first: in a frozen executable, pm4py's alignment workers are
    # started by re-running this very program.
    multiprocessing.freeze_support()
    _prepare_frozen_runtime()

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        env_port = _env_port()
        explicit = args.port is not None or env_port is not None
        requested = args.port if args.port is not None else (env_port or Config.DEFAULT_PORT)
        if not 0 < requested < 65536:
            raise LauncherError(f'{requested} is not a valid port number.')

        port, instance = choose_port(args.host, requested, explicit)
        url = public_url(args.host, port)

        if instance is not None:
            version = instance.get('version')
            name = f'ProSiT {version}' if version else 'ProSiT'
            print(f'{name} is already running at {url}')
            if not args.no_browser:
                webbrowser.open(url)
            return 0

        configure_logging()
        from waitress import create_server
        from .app import create_app

        app = create_app(args.data_dir)
        try:
            server = create_server(app, host=args.host, port=port, threads=SERVER_THREADS)
        except OSError as exc:
            raise LauncherError(f'Cannot listen on {args.host}:{port}: {exc}') from exc
    except LauncherError as exc:
        print(f'{APP_NAME}: {exc}', file=sys.stderr)
        return 2

    print(f'ProSiT {__version__} is running at {url}')
    print(f'Data directory: {app.config["DATA_DIR"]}')
    print('Press Ctrl+C to stop.', flush=True)

    if not args.no_browser:
        # The socket is already bound, so a request arriving before the loop
        # below starts simply waits in the accept queue.
        opener = threading.Timer(0.5, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()

    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
