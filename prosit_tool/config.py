"""Constants, data locations and Flask settings for prosit-tool.

Nothing in this module touches the file system at import time: directories are
created, and the secret key is read or generated, only when an application is
built by :func:`prosit_tool.app.create_app`.
"""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = 'prosit-tool'

# Environment variable that moves every file the tool writes somewhere else.
ENV_DATA_DIR = 'PROSIT_TOOL_DATA_DIR'


class Config:
    # --- Discovery defaults --------------------------------------------------
    DEFAULT_NOISE_THRESHOLD = 0.2
    MAX_NOISE_THRESHOLD = 1.0

    DEFAULT_MAX_DEPTH_TREE = 0
    MAX_DEPTH_TREE = 5

    DEFAULT_GRACE_PERIOD = 1000
    MIN_GRACE_PERIOD = 1

    # Discovery options of prosit-pm exposed in the upload form.
    DEFAULT_MULTITASKING_THR = 0.05
    DEFAULT_RANDOM_STATE = 72
    DEFAULT_ATTRIBUTE_MODE = 'distribution'

    # --- Simulation defaults --------------------------------------------------
    MIN_INSTANCES = 1
    MAX_INSTANCES = 10_000
    DEFAULT_INSTANCES = 100

    # --- Web/server settings --------------------------------------------------
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
    DEFAULT_HOST = '127.0.0.1'
    DEFAULT_PORT = 5050
    POOL_RECYCLE = 300


@dataclass(frozen=True)
class DataPaths:
    """Everything one installation writes lives under ``root``.

    The layout is the one a source checkout has always used (``uploads/``,
    ``simulations/``, ``instance/prosit.db``), so pointing ``root`` at an old
    checkout or at the three volumes of the Docker setup picks up its sessions.
    """

    root: Path

    @property
    def uploads(self) -> Path:
        return self.root / 'uploads'

    @property
    def simulations(self) -> Path:
        return self.root / 'simulations'

    @property
    def instance(self) -> Path:
        return self.root / 'instance'

    @property
    def database(self) -> Path:
        return self.instance / 'prosit.db'

    @property
    def secret_key_file(self) -> Path:
        return self.instance / 'secret_key'

    def create(self) -> 'DataPaths':
        for directory in (self.uploads, self.simulations, self.instance):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def default_data_dir() -> Path:
    """``$PROSIT_TOOL_DATA_DIR`` if set, else the per-user data directory.

    Linux: ``~/.local/share/prosit-tool``; macOS: ``~/Library/Application
    Support/prosit-tool``; Windows: ``%LOCALAPPDATA%\\prosit-tool``.
    """
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser()
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def resolve_data_paths(data_dir=None) -> DataPaths:
    """Absolute data locations for ``data_dir`` (default: :func:`default_data_dir`)."""
    root = Path(data_dir).expanduser() if data_dir else default_data_dir()
    return DataPaths(root.resolve())


def resolve_database_url(paths: DataPaths, database_url=None) -> str:
    """Explicit URL, else ``$DATABASE_URL``, else SQLite inside the data dir."""
    url = database_url or os.environ.get('DATABASE_URL')
    if url:
        return url
    return 'sqlite:///' + paths.database.as_posix()


def resolve_secret_key(paths: DataPaths) -> str:
    """``$SESSION_SECRET`` if set, else a key generated once per data dir.

    The tool keeps no Flask session and sets no cookie, so nothing depends on
    this key today; it is still generated randomly and kept private (mode 600)
    so that a future use of signed cookies starts from a sound default without
    asking every user to configure a secret before the first start.
    """
    secret = os.environ.get('SESSION_SECRET')
    if secret:
        return secret

    key_file = paths.secret_key_file

    def stored():
        try:
            return key_file.read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            return ''

    existing = stored()
    if existing:
        return existing

    key = secrets.token_hex(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Created by another process between the read above and this write.
        existing = stored()
        if existing:
            return existing
        fd = os.open(key_file, os.O_WRONLY | os.O_TRUNC)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(key)
    return key
