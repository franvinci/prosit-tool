"""Input validators that translate raw query/body values into typed values.

Each ``validate_*`` returns ``(value, error)``: ``error`` is ``None`` on
success, or a short string on failure. Endpoints can ``return jsonify({'error':
err}), 400`` instead of letting ``int(request.args.get(...))`` raise a 500.

A value that is missing gets its default; a value that is present but wrong is
an error. It is never quietly replaced: the caller asked for something specific
and has to be told it was not used.
"""

from datetime import datetime
from typing import Tuple

from .config import Config


def _coerce_int(raw, default):
    if raw is None or raw == '':
        return default, None
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, f'expected an integer, got {raw!r}'


def _coerce_float(raw, default):
    if raw is None or raw == '':
        return default, None
    try:
        return float(raw), None
    except (TypeError, ValueError):
        return None, f'expected a number, got {raw!r}'


def _coerce_bool(raw, default=False):
    if raw is None:
        return default
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def validate_noise_threshold(raw) -> Tuple[float, str | None]:
    value, err = _coerce_float(raw, Config.DEFAULT_NOISE_THRESHOLD)
    if err:
        return Config.DEFAULT_NOISE_THRESHOLD, err
    if not 0.0 <= value <= Config.MAX_NOISE_THRESHOLD:
        return Config.DEFAULT_NOISE_THRESHOLD, (
            f'noise_threshold must be between 0 and {Config.MAX_NOISE_THRESHOLD}'
        )
    return value, None


def validate_max_depth_tree(raw) -> Tuple[int, str | None]:
    value, err = _coerce_int(raw, Config.DEFAULT_MAX_DEPTH_TREE)
    if err:
        return Config.DEFAULT_MAX_DEPTH_TREE, err
    if not 0 <= value <= Config.MAX_DEPTH_TREE:
        return Config.DEFAULT_MAX_DEPTH_TREE, (
            f'max_depth_tree must be between 0 and {Config.MAX_DEPTH_TREE}'
        )
    return value, None


def validate_grace_period(raw) -> Tuple[int, str | None]:
    value, err = _coerce_int(raw, Config.DEFAULT_GRACE_PERIOD)
    if err:
        return Config.DEFAULT_GRACE_PERIOD, err
    if value < Config.MIN_GRACE_PERIOD:
        return Config.DEFAULT_GRACE_PERIOD, (
            f'grace_period must be at least {Config.MIN_GRACE_PERIOD}'
        )
    return value, None


def validate_multitasking_thr(raw) -> Tuple[float, str | None]:
    value, err = _coerce_float(raw, Config.DEFAULT_MULTITASKING_THR)
    if err:
        return Config.DEFAULT_MULTITASKING_THR, err
    if not 0.0 <= value <= 1.0:
        return Config.DEFAULT_MULTITASKING_THR, 'multitasking_thr must be between 0 and 1'
    return value, None


def validate_random_state(raw) -> Tuple[int, str | None]:
    value, err = _coerce_int(raw, Config.DEFAULT_RANDOM_STATE)
    if err:
        return Config.DEFAULT_RANDOM_STATE, err
    return value, None


_VALID_ATTRIBUTE_MODES = ('distribution', 'empirical')


def validate_attribute_mode(raw) -> Tuple[str, str | None]:
    if raw is None or raw == '':
        return Config.DEFAULT_ATTRIBUTE_MODE, None
    value = str(raw).strip().lower()
    if value not in _VALID_ATTRIBUTE_MODES:
        return Config.DEFAULT_ATTRIBUTE_MODE, (
            f"attribute_mode must be one of {_VALID_ATTRIBUTE_MODES}"
        )
    return value, None


def validate_num_instances(raw) -> Tuple[int, str | None]:
    """Strict: bad input returns (None, error) so the caller can 400 cleanly."""
    if raw is None or raw == '':
        return Config.DEFAULT_INSTANCES, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f'num_instances must be an integer, got {raw!r}'
    if not Config.MIN_INSTANCES <= value <= Config.MAX_INSTANCES:
        return None, f'num_instances must be between {Config.MIN_INSTANCES} and {Config.MAX_INSTANCES}'
    return value, None


def parse_bool(raw, default=False) -> bool:
    return _coerce_bool(raw, default)


_DISCOVERY_OPTIONS = (
    ('max_depth_tree', validate_max_depth_tree),
    ('grace_period', validate_grace_period),
    ('multitasking_thr', validate_multitasking_thr),
    ('random_state', validate_random_state),
    ('attribute_mode', validate_attribute_mode),
)
_DISCOVERY_FLAGS = ('incremental_discovery', 'enable_multitasking', 'use_workload_features')


def validate_discovery_options(args) -> Tuple[dict, str | None]:
    """Every option of the discovery request, as keyword arguments.

    ``error`` names the first option that is present but invalid.
    """
    options = {}
    for name, validator in _DISCOVERY_OPTIONS:
        value, err = validator(args.get(name))
        if err:
            return {}, err if err.startswith(name) else f'{name}: {err}'
        options[name] = value
    for name in _DISCOVERY_FLAGS:
        options[name] = parse_bool(args.get(name))
    return options, None


def validate_run_id(raw) -> Tuple[int | None, str | None]:
    """``None`` when no run is named; an error when the id is not a whole number."""
    if raw is None or raw == '':
        return None, None
    if isinstance(raw, bool):
        return None, f'run_id must be an integer, got {raw!r}'
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, f'run_id must be an integer, got {raw!r}'


def validate_start_timestamp(raw) -> Tuple[datetime | None, str | None]:
    """Start of a simulation; ``None`` (the caller uses "now") when not given.

    The simulator works on the wall clock of the event log: its calendars say
    "Monday at 9", with no time zone. A UTC offset in the request is therefore
    dropped rather than converted, so that "10:00+02:00" starts at 10 o'clock
    of the calendars, which is what the sender is looking at.
    """
    if raw is None or raw == '':
        return None, None
    if not isinstance(raw, str):
        return None, f'start_timestamp must be an ISO 8601 date and time, got {raw!r}'
    try:
        value = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
    except ValueError:
        return None, f'start_timestamp must be an ISO 8601 date and time, got {raw!r}'
    return value.replace(tzinfo=None), None
