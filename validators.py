"""Input validators that translate raw query/body values into typed values.

Each ``validate_*`` returns ``(value, error)``: ``error`` is ``None`` on
success, or a short string on failure. Endpoints can ``return jsonify({'error':
err}), 400`` instead of letting ``int(request.args.get(...))`` raise a 500.
"""

from typing import Tuple

from config import Config


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
    if value < 0:
        value = 0
    if value > Config.MAX_DEPTH_TREE:
        value = Config.MAX_DEPTH_TREE
    return value, None


def validate_grace_period(raw) -> Tuple[int, str | None]:
    value, err = _coerce_int(raw, Config.DEFAULT_GRACE_PERIOD)
    if err:
        return Config.DEFAULT_GRACE_PERIOD, err
    if value < Config.MIN_GRACE_PERIOD:
        return Config.DEFAULT_GRACE_PERIOD, None
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
