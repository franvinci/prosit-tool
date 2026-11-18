"""Distribution format conversion between the UI shape and ProSiT JSON shape.

The web UI emits distributions like::

    {"distribution": "norm", "parameters": {"mean": 15, "std": 5, "min": 0, "max": 60}}

ProSiT consumes them in this shape::

    {"dist_name": "norm", "params": [15, 5], "min_value": 0, "max_value": 60, "mean_value": 15}

Before this module, four near-identical translations of the inner ``if dist ==
'fixed'/'norm'/'expon'/'uniform'`` ladder lived in ``routes.py`` (one each for
execution times, waiting times, inter-arrival, and data attributes), and a
near-duplicate inverse lived in ``prosit_integration.py``. They've all been
collapsed into the helpers below.

Decision-tree distributions (UI shape ``{"0": {...}, "1": {...}, ...}`` where
each leaf carries its own ``dist``) are flattened by ``transform_distribution_tree``.
"""

from typing import Any

# Defaults used when a parameter is missing from the UI payload. Kept as
# constants because they were sprinkled as magic numbers across the original
# four duplicated blocks, all using the same values.
DEFAULT_MEAN = 15.0
DEFAULT_STD = 5.0
DEFAULT_MIN = 0.0
DEFAULT_MAX = 60.0
DEFAULT_FIXED = 1.0

SUPPORTED_DISTRIBUTIONS = ('fixed', 'norm', 'expon', 'uniform', 'lognorm', 'gamma')

DEFAULT_LOGNORM_SHAPE = 0.5
DEFAULT_LOGNORM_SCALE = 1.0

DEFAULT_GAMMA_SHAPE = 2.0
DEFAULT_GAMMA_SCALE = 1.0


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def distribution_to_prosit(dist_name: str, param_values: dict | None) -> dict:
    """Translate one UI-style distribution into ProSiT JSON shape.

    ``param_values`` is the inner ``parameters`` dict from the UI. Tolerates the
    legacy alias keys (``min_value``/``max_value``/``mean_value``) alongside
    the modern short keys (``min``/``max``/``mean``).

    Unknown distribution names fall back to ``fixed`` with a 1.0 value, which
    matches the historical behaviour.
    """
    pv = param_values or {}

    def get(*keys, default=None):
        for k in keys:
            if k in pv and pv[k] is not None:
                return pv[k]
        return default

    min_val = _coerce_float(get('min', 'min_value', default=DEFAULT_FIXED), DEFAULT_FIXED)
    max_val = _coerce_float(get('max', 'max_value', default=DEFAULT_FIXED), DEFAULT_FIXED)
    mean_val = _coerce_float(get('mean', 'mean_value', default=DEFAULT_FIXED), DEFAULT_FIXED)

    if dist_name == 'fixed':
        value = _coerce_float(get('value', 'mean', 'mean_value', default=DEFAULT_FIXED), DEFAULT_FIXED)
        return {
            'dist_name': 'fixed',
            'params': [value],
            'min_value': value,
            'max_value': value,
            'mean_value': value,
        }
    if dist_name == 'norm':
        mean = _coerce_float(get('mean', 'mean_value', default=DEFAULT_MEAN), DEFAULT_MEAN)
        std = _coerce_float(get('std', default=DEFAULT_STD), DEFAULT_STD)
        return {
            'dist_name': 'norm',
            'params': [mean, std],
            'min_value': _coerce_float(get('min', 'min_value', default=DEFAULT_FIXED), DEFAULT_FIXED),
            'max_value': _coerce_float(get('max', 'max_value', default=DEFAULT_MAX), DEFAULT_MAX),
            'mean_value': mean,
        }
    if dist_name == 'expon':
        mean = _coerce_float(get('mean', 'mean_value', default=DEFAULT_MEAN), DEFAULT_MEAN)
        return {
            'dist_name': 'expon',
            'params': [0.0, mean],
            'min_value': _coerce_float(get('min', 'min_value', default=DEFAULT_FIXED), DEFAULT_FIXED),
            'max_value': _coerce_float(get('max', 'max_value', default=DEFAULT_MAX), DEFAULT_MAX),
            'mean_value': mean,
        }
    if dist_name == 'uniform':
        low = _coerce_float(get('min', 'min_value', default=DEFAULT_MIN), DEFAULT_MIN)
        high = _coerce_float(get('max', 'max_value', default=DEFAULT_MAX), DEFAULT_MAX)
        return {
            'dist_name': 'uniform',
            'params': [low, high],
            'min_value': low,
            'max_value': high,
            'mean_value': (low + high) / 2.0,
        }
    if dist_name == 'lognorm':
        # scipy.stats.lognorm uses (s, loc, scale). The UI exposes shape (s),
        # loc (default 0), and scale; mean is roughly scale * exp(s^2 / 2).
        shape = _coerce_float(get('shape', 's', default=DEFAULT_LOGNORM_SHAPE), DEFAULT_LOGNORM_SHAPE)
        loc = _coerce_float(get('loc', default=0.0), 0.0)
        scale = _coerce_float(get('scale', default=DEFAULT_LOGNORM_SCALE), DEFAULT_LOGNORM_SCALE)
        return {
            'dist_name': 'lognorm',
            'params': [shape, loc, scale],
            'min_value': _coerce_float(get('min', 'min_value', default=DEFAULT_MIN), DEFAULT_MIN),
            'max_value': _coerce_float(get('max', 'max_value', default=DEFAULT_MAX), DEFAULT_MAX),
            'mean_value': _coerce_float(get('mean', 'mean_value', default=scale), scale),
        }
    if dist_name == 'gamma':
        # scipy.stats.gamma uses (a, loc, scale). Mean = a*scale (when loc=0)
        # and std = sqrt(a)*scale, so the more user-friendly mean/std fields can
        # be converted back to (shape, scale) when both are provided.
        loc = _coerce_float(get('loc', default=0.0), 0.0)
        mean_in = get('mean', 'mean_value')
        std_in = get('std')
        if mean_in is not None and std_in is not None:
            try:
                mean_f = float(mean_in)
                std_f = float(std_in)
            except (TypeError, ValueError):
                mean_f, std_f = None, None
            if mean_f and std_f and mean_f > 0 and std_f > 0:
                shape = (mean_f ** 2) / (std_f ** 2)
                scale = (std_f ** 2) / mean_f
            else:
                shape = _coerce_float(get('shape', 'a', default=DEFAULT_GAMMA_SHAPE), DEFAULT_GAMMA_SHAPE)
                scale = _coerce_float(get('scale', default=DEFAULT_GAMMA_SCALE), DEFAULT_GAMMA_SCALE)
        else:
            shape = _coerce_float(get('shape', 'a', default=DEFAULT_GAMMA_SHAPE), DEFAULT_GAMMA_SHAPE)
            scale = _coerce_float(get('scale', default=DEFAULT_GAMMA_SCALE), DEFAULT_GAMMA_SCALE)
        return {
            'dist_name': 'gamma',
            'params': [shape, loc, scale],
            'min_value': _coerce_float(get('min', 'min_value', default=DEFAULT_MIN), DEFAULT_MIN),
            'max_value': _coerce_float(get('max', 'max_value', default=DEFAULT_MAX), DEFAULT_MAX),
            'mean_value': shape * scale,
        }

    return {
        'dist_name': 'fixed',
        'params': [DEFAULT_FIXED],
        'min_value': min_val,
        'max_value': max_val,
        'mean_value': mean_val,
    }


def distribution_from_prosit(dist_name: str, params: list, min_val: Any,
                             max_val: Any, mean_val: Any) -> dict:
    """Inverse of ``distribution_to_prosit``: ProSiT scalars → UI parameters.

    Returns the ``parameters`` payload that pairs with a ``distribution`` key
    in the UI shape. The caller wraps it in
    ``{"distribution": dist_name, "parameters": <result>}``.
    """
    base = {
        'min_value': _coerce_float(min_val, DEFAULT_FIXED),
        'max_value': _coerce_float(max_val, DEFAULT_FIXED),
        'mean_value': _coerce_float(mean_val, DEFAULT_FIXED),
    }
    params = params or []

    if dist_name == 'fixed':
        base['value'] = _coerce_float(params[0] if params else DEFAULT_FIXED, DEFAULT_FIXED)
    elif dist_name == 'norm':
        base['mean'] = _coerce_float(params[0] if len(params) > 0 else DEFAULT_MEAN, DEFAULT_MEAN)
        base['std'] = _coerce_float(params[1] if len(params) > 1 else DEFAULT_STD, DEFAULT_STD)
    elif dist_name == 'expon':
        # ProSiT stores [loc, scale]; the UI displays mean = scale.
        scale_val = _coerce_float(params[1] if len(params) > 1 else mean_val, DEFAULT_MEAN)
        base['scale'] = scale_val
        base['mean'] = scale_val
    elif dist_name == 'uniform':
        if len(params) >= 2:
            base['min'] = _coerce_float(params[0], DEFAULT_MIN)
            base['max'] = _coerce_float(params[1], DEFAULT_MAX)
        else:
            base['min'] = base['min_value']
            base['max'] = base['max_value']
    elif dist_name == 'lognorm':
        # scipy.stats.lognorm.params == (shape s, loc, scale).
        base['shape'] = _coerce_float(params[0] if len(params) > 0 else DEFAULT_LOGNORM_SHAPE, DEFAULT_LOGNORM_SHAPE)
        base['loc'] = _coerce_float(params[1] if len(params) > 1 else 0.0, 0.0)
        base['scale'] = _coerce_float(params[2] if len(params) > 2 else DEFAULT_LOGNORM_SCALE, DEFAULT_LOGNORM_SCALE)
    elif dist_name == 'gamma':
        # scipy.stats.gamma.params == (a/shape, loc, scale). The UI surfaces
        # (Mean, Std) since users rarely think in shape/scale terms.
        shape = _coerce_float(params[0] if len(params) > 0 else DEFAULT_GAMMA_SHAPE, DEFAULT_GAMMA_SHAPE)
        scale = _coerce_float(params[2] if len(params) > 2 else DEFAULT_GAMMA_SCALE, DEFAULT_GAMMA_SCALE)
        base['shape'] = shape
        base['loc'] = _coerce_float(params[1] if len(params) > 1 else 0.0, 0.0)
        base['scale'] = scale
        base['mean'] = shape * scale
        base['std'] = (shape ** 0.5) * scale
    return base


def normalize_distribution_object(dist_obj: Any, leaf_value: Any = None) -> Any:
    """Normalize a distribution dict (UI shape) into ProSiT shape.

    Accepts both ``params`` as a list (already ProSiT-aligned) and as a dict
    (UI shape). Returns the input untouched if it isn't a dict.
    """
    if not isinstance(dist_obj, dict):
        return dist_obj

    dist_name = dist_obj.get('dist_name', 'expon')
    params_raw = dist_obj.get('params', {})

    if isinstance(params_raw, list):
        return _normalize_from_list(dist_name, params_raw, dist_obj, leaf_value)
    return _normalize_from_object(dist_name, params_raw, dist_obj, leaf_value)


def _normalize_from_list(dist_name, params_raw, dist_obj, leaf_value):
    leaf_default = leaf_value if leaf_value is not None else DEFAULT_FIXED
    result = {'dist_name': dist_name}
    if dist_name == 'fixed':
        value = params_raw[0] if params_raw else leaf_default
        result['params'] = [value]
        result['min_value'] = dist_obj.get('min_value', value)
        result['max_value'] = dist_obj.get('max_value', value)
        result['mean_value'] = dist_obj.get('mean_value', value)
    elif dist_name == 'norm':
        mean = params_raw[0] if len(params_raw) > 0 else dist_obj.get('mean_value', leaf_value or DEFAULT_MEAN)
        std = params_raw[1] if len(params_raw) > 1 else DEFAULT_STD
        result['params'] = [mean, std]
        result['min_value'] = dist_obj.get('min_value', DEFAULT_MIN)
        result['max_value'] = dist_obj.get('max_value', DEFAULT_MAX)
        result['mean_value'] = mean
    elif dist_name == 'expon':
        loc = params_raw[0] if len(params_raw) > 0 else 0.0
        scale = params_raw[1] if len(params_raw) > 1 else dist_obj.get('mean_value', leaf_value or DEFAULT_MEAN)
        result['params'] = [loc, scale]
        result['min_value'] = dist_obj.get('min_value', DEFAULT_MIN)
        result['max_value'] = dist_obj.get('max_value', DEFAULT_MAX)
        result['mean_value'] = scale
    elif dist_name == 'uniform':
        low = params_raw[0] if len(params_raw) > 0 else dist_obj.get('min_value', DEFAULT_MIN)
        high = params_raw[1] if len(params_raw) > 1 else dist_obj.get('max_value', DEFAULT_MAX)
        result['params'] = [low, high]
        result['min_value'] = low
        result['max_value'] = high
        result['mean_value'] = (low + high) / 2.0
    elif dist_name == 'lognorm':
        # scipy.stats.lognorm: (s, loc, scale).
        s = params_raw[0] if len(params_raw) > 0 else DEFAULT_LOGNORM_SHAPE
        loc = params_raw[1] if len(params_raw) > 1 else 0.0
        scale = params_raw[2] if len(params_raw) > 2 else DEFAULT_LOGNORM_SCALE
        result['params'] = [s, loc, scale]
        result['min_value'] = dist_obj.get('min_value', DEFAULT_MIN)
        result['max_value'] = dist_obj.get('max_value', DEFAULT_MAX)
        result['mean_value'] = dist_obj.get('mean_value', scale)
    elif dist_name == 'gamma':
        # scipy.stats.gamma: (a, loc, scale).
        shape = params_raw[0] if len(params_raw) > 0 else DEFAULT_GAMMA_SHAPE
        loc = params_raw[1] if len(params_raw) > 1 else 0.0
        scale = params_raw[2] if len(params_raw) > 2 else DEFAULT_GAMMA_SCALE
        result['params'] = [shape, loc, scale]
        result['min_value'] = dist_obj.get('min_value', DEFAULT_MIN)
        result['max_value'] = dist_obj.get('max_value', DEFAULT_MAX)
        result['mean_value'] = dist_obj.get('mean_value', shape * scale)
    else:
        # Unknown dist_name (e.g. 'beta'): preserve incoming fields
        # so prosit-pm's dict_to_decrules doesn't blow up on missing 'params'.
        leaf_default_value = leaf_value if leaf_value is not None else DEFAULT_FIXED
        result['params'] = list(params_raw) if params_raw else dist_obj.get('params', [leaf_default_value])
        result['min_value'] = dist_obj.get('min_value', DEFAULT_MIN)
        result['max_value'] = dist_obj.get('max_value', DEFAULT_MAX)
        result['mean_value'] = dist_obj.get('mean_value', leaf_default_value)
    return result


def _normalize_from_object(dist_name, params_raw, dist_obj, leaf_value):
    if isinstance(params_raw, dict):
        mean = params_raw.get('mean', dist_obj.get('mean_value', leaf_value or DEFAULT_MEAN))
        std = params_raw.get('std', DEFAULT_STD)
        min_v = params_raw.get('min', dist_obj.get('min_value', DEFAULT_MIN))
        max_v = params_raw.get('max', dist_obj.get('max_value', DEFAULT_MAX))
        fixed_v = params_raw.get('value', mean)
    else:
        mean, std, min_v, max_v, fixed_v = (leaf_value or DEFAULT_MEAN), DEFAULT_STD, DEFAULT_MIN, DEFAULT_MAX, (leaf_value or DEFAULT_MEAN)

    result = {'dist_name': dist_name}
    if dist_name == 'fixed':
        result['params'] = [fixed_v]
        result['min_value'] = fixed_v
        result['max_value'] = fixed_v
        result['mean_value'] = fixed_v
    elif dist_name == 'norm':
        result['params'] = [mean, std]
        result['min_value'] = min_v
        result['max_value'] = max_v
        result['mean_value'] = mean
    elif dist_name == 'expon':
        result['params'] = [0.0, mean]
        result['min_value'] = min_v
        result['max_value'] = max_v
        result['mean_value'] = mean
    elif dist_name == 'uniform':
        result['params'] = [min_v, max_v]
        result['min_value'] = min_v
        result['max_value'] = max_v
        result['mean_value'] = (min_v + max_v) / 2.0
    elif dist_name == 'lognorm':
        # UI-shape input for lognorm carries shape/scale (and optional loc).
        if isinstance(params_raw, dict):
            shape = params_raw.get('shape', params_raw.get('s', DEFAULT_LOGNORM_SHAPE))
            loc = params_raw.get('loc', 0.0)
            scale = params_raw.get('scale', DEFAULT_LOGNORM_SCALE)
        else:
            shape, loc, scale = DEFAULT_LOGNORM_SHAPE, 0.0, DEFAULT_LOGNORM_SCALE
        result['params'] = [shape, loc, scale]
        result['min_value'] = min_v
        result['max_value'] = max_v
        result['mean_value'] = dist_obj.get('mean_value', scale)
    elif dist_name == 'gamma':
        if isinstance(params_raw, dict):
            shape = params_raw.get('shape', params_raw.get('a', DEFAULT_GAMMA_SHAPE))
            loc = params_raw.get('loc', 0.0)
            scale = params_raw.get('scale', DEFAULT_GAMMA_SCALE)
        else:
            shape, loc, scale = DEFAULT_GAMMA_SHAPE, 0.0, DEFAULT_GAMMA_SCALE
        result['params'] = [shape, loc, scale]
        result['min_value'] = min_v
        result['max_value'] = max_v
        result['mean_value'] = dist_obj.get('mean_value', shape * scale)
    else:
        # Unknown dist_name: preserve whatever the caller supplied so the
        # downstream prosit JSON keeps its 'params' list (otherwise simulate
        # crashes with KeyError: 'params').
        existing_params = dist_obj.get('params')
        if isinstance(existing_params, list):
            result['params'] = existing_params
        else:
            result['params'] = [mean]
        result['min_value'] = min_v
        result['max_value'] = max_v
        result['mean_value'] = dist_obj.get('mean_value', mean)
    return result


def transform_distribution_tree(tree: Any) -> Any:
    """Normalize every leaf of a decision tree (shape ``{'0': ..., '1': ...}``).

    Handles both leaf nodes (with ``value`` and optional ``dist``) and split
    nodes (with ``feature``, ``threshold``, ``children``). Unknown node shapes
    are passed through unchanged.
    """
    if not isinstance(tree, dict):
        return tree
    normalized = {}
    for key, node in tree.items():
        if isinstance(node, dict) and 'value' in node:
            leaf_value = node.get('value')
            default_dist = {
                'dist_name': 'expon',
                'params': {'mean': leaf_value if leaf_value is not None else DEFAULT_MEAN},
            }
            dist_obj = node.get('dist', default_dist)
            normalized[key] = {
                'value': leaf_value,
                'dist': normalize_distribution_object(dist_obj, leaf_value),
            }
        elif isinstance(node, dict) and 'feature' in node:
            normalized[key] = {
                'feature': node.get('feature'),
                'threshold': node.get('threshold'),
                'children': node.get('children', {}),
            }
        else:
            normalized[key] = node
    return normalized


def app_entry_to_prosit(params: dict) -> dict:
    """Convert one ``{distribution, parameters}`` UI entry (or a tree) to ProSiT.

    Replaces the four near-duplicated bodies that previously lived inline in
    ``convert_app_to_prosit_format``: execution time, waiting time, inter-arrival,
    and data attributes all flow through this single helper now.
    """
    if isinstance(params, dict) and '0' in params:
        return transform_distribution_tree(params)

    dist = params.get('distribution', 'fixed') if isinstance(params, dict) else 'fixed'
    pv = params.get('parameters', {}) if isinstance(params, dict) else {}
    return distribution_to_prosit(dist, pv)
