"""Distribution format conversion between the UI shape and prosit-pm's JSON shape.

The web UI exchanges distributions like::

    {"distribution": "norm", "parameters": {"mean": 15, "std": 5, "min": 0, "max": 60}}

prosit-pm stores them like::

    {"dist_name": "norm", "params": [15, 5], "min_value": 0, "max_value": 60, "mean_value": 15}

``params`` are the positional arguments of the ``scipy.stats`` distribution of
the same name, exactly as ``scipy`` fitted them. The UI shows the quantities a
person reasons about instead:

    =========  =====================  =============================================
    family     prosit-pm ``params``   UI parameters
    =========  =====================  =============================================
    fixed      (value,)               value
    norm       (mean, std)            mean, std
    expon      (loc, scale)           mean = loc + scale, loc
    uniform    (loc, scale)           min = loc, max = loc + scale
    lognorm    (s, loc, scale)        shape, loc, scale
    gamma      (a, loc, scale)        mean = loc + a*scale, std = sqrt(a)*scale, loc
    =========  =====================  =============================================

``min_value`` / ``max_value`` clip the sampled values (UI: ``min`` / ``max``).

The two directions are exact inverses, and ``merge_app_entry`` does not even
convert an entry that comes back from the UI the way it was sent. Together they
make a what-if scenario saved without touching a distribution simulate exactly
like the scenario it was copied from: the UI sends every distribution of a
scenario back on each save, edited or not.

In rules mode a distribution is a decision tree (``{"0": {...}, "1": {...}}``)
whose leaves carry their own ``dist``; ``transform_distribution_tree`` converts
those. A leaf the user never opened still has prosit-pm's ``params`` list and
is passed through untouched; a leaf opened in the editor has UI parameters and
goes through the same conversion as a plain distribution.
"""

import math
from typing import Any

import scipy.stats

# Used only when the UI payload carries no value for a parameter.
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

# When the UI gives no clipping bounds (it does not, right after the user picks
# another family), clip only the extreme tails so that the distribution keeps
# the shape and the mean the user asked for.
_TAIL = 0.0005


def _number(value: Any, default=None):
    """``float(value)`` when it is a finite number, else ``default``."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _coerce_float(value: Any, default: float) -> float:
    return _number(value, default)


def _first(values: dict, *keys):
    """First finite number found under ``keys``, or ``None``."""
    for key in keys:
        number = _number(values.get(key))
        if number is not None:
            return number
    return None


def _or(value, default):
    return default if value is None else value


def _scipy_params(dist_name: str, values: dict, leaf_value=None):
    """UI parameters -> ``(params, mean_value)`` in prosit-pm's layout.

    ``leaf_value`` is the value of the tree leaf the distribution belongs to
    (``None`` outside trees); it stands in for a missing central value.
    """
    centre = _first(values, 'mean', 'mean_value')
    if centre is None:
        centre = _number(leaf_value)

    if dist_name == 'fixed':
        value = _first(values, 'value')
        if value is None:
            value = _or(centre, DEFAULT_FIXED)
        return [value], value

    if dist_name == 'norm':
        mean = _or(centre, DEFAULT_MEAN)
        std = abs(_or(_first(values, 'std'), DEFAULT_STD))
        return [mean, std], mean

    if dist_name == 'expon':
        mean = _or(centre, DEFAULT_MEAN)
        loc = _or(_first(values, 'loc'), 0.0)
        if mean <= loc:
            # A mean at or below the shift leaves no room for the exponential
            # part: read it as a plain exponential with that mean.
            loc = 0.0
        return [loc, max(mean - loc, 0.0)], mean

    if dist_name == 'uniform':
        low = _or(_first(values, 'min', 'min_value'), DEFAULT_MIN)
        high = _or(_first(values, 'max', 'max_value'), DEFAULT_MAX)
        if high < low:
            low, high = high, low
        return [low, high - low], (low + high) / 2.0

    if dist_name == 'lognorm':
        shape = abs(_or(_first(values, 'shape', 's'), DEFAULT_LOGNORM_SHAPE))
        loc = _or(_first(values, 'loc'), 0.0)
        scale = abs(_or(_first(values, 'scale'), DEFAULT_LOGNORM_SCALE))
        return [shape, loc, scale], _or(centre, scale)

    if dist_name == 'gamma':
        loc = _or(_first(values, 'loc'), 0.0)
        mean = _first(values, 'mean', 'mean_value')
        std = _first(values, 'std')
        # The UI edits Mean and Std Dev; shape and scale follow from them.
        if mean is not None and std is not None and mean > loc and std > 0:
            centred = mean - loc
            shape = centred ** 2 / std ** 2
            scale = std ** 2 / centred
        else:
            shape = abs(_or(_first(values, 'shape', 'a'), DEFAULT_GAMMA_SHAPE))
            scale = abs(_or(_first(values, 'scale'), DEFAULT_GAMMA_SCALE))
        return [shape, loc, scale], loc + shape * scale

    raise KeyError(dist_name)


def _natural_bounds(dist_name: str, params: list):
    """Bounds that leave ``dist_name(*params)`` essentially unclipped."""
    if dist_name == 'fixed':
        return params[0], params[0]
    if dist_name == 'uniform':
        return params[0], params[0] + params[1]
    try:
        low, high = getattr(scipy.stats, dist_name).ppf([_TAIL, 1.0 - _TAIL], *params)
    except Exception:
        return DEFAULT_MIN, DEFAULT_MAX
    low, high = _number(low), _number(high)
    if low is None or high is None:
        return DEFAULT_MIN, DEFAULT_MAX
    return low, high


def _bounds(dist_name: str, params: list, values: dict):
    """Clipping bounds: the ones given, else the natural ones of the family."""
    if dist_name in ('fixed', 'uniform'):
        # For these two the bounds *are* the distribution.
        return _natural_bounds(dist_name, params)
    low = _first(values, 'min', 'min_value')
    high = _first(values, 'max', 'max_value')
    if low is None or high is None:
        natural_low, natural_high = _natural_bounds(dist_name, params)
        low = _or(low, natural_low)
        high = _or(high, natural_high)
    if high < low:
        low, high = high, low
    return low, high


def distribution_to_prosit(dist_name: str, param_values: dict | None, leaf_value=None) -> dict:
    """Translate one UI-style distribution into prosit-pm's JSON shape.

    ``param_values`` is the inner ``parameters`` dict from the UI. The short
    keys the UI writes when the user edits a field (``min``/``max``/``mean``)
    win over the ``*_value`` keys it received from the server.

    Unknown distribution names fall back to ``fixed`` with a 1.0 value.
    """
    values = param_values if isinstance(param_values, dict) else {}
    try:
        params, mean_value = _scipy_params(dist_name, values, leaf_value)
    except KeyError:
        return {
            'dist_name': 'fixed',
            'params': [DEFAULT_FIXED],
            'min_value': _or(_first(values, 'min', 'min_value'), DEFAULT_FIXED),
            'max_value': _or(_first(values, 'max', 'max_value'), DEFAULT_FIXED),
            'mean_value': _or(_first(values, 'mean', 'mean_value'), DEFAULT_FIXED),
        }
    min_value, max_value = _bounds(dist_name, params, values)
    return {
        'dist_name': dist_name,
        'params': params,
        'min_value': min_value,
        'max_value': max_value,
        'mean_value': mean_value,
    }


def distribution_from_prosit(dist_name: str, params: list, min_val: Any,
                             max_val: Any, mean_val: Any) -> dict:
    """Inverse of ``distribution_to_prosit``: prosit-pm scalars -> UI parameters.

    Returns the ``parameters`` payload that pairs with a ``distribution`` key
    in the UI shape. The caller wraps it in
    ``{"distribution": dist_name, "parameters": <result>}``.
    """
    base = {
        'min_value': _coerce_float(min_val, DEFAULT_FIXED),
        'max_value': _coerce_float(max_val, DEFAULT_FIXED),
        'mean_value': _coerce_float(mean_val, DEFAULT_FIXED),
    }
    params = list(params or [])

    def param(index, default):
        return _coerce_float(params[index], default) if len(params) > index else default

    if dist_name == 'fixed':
        base['value'] = param(0, DEFAULT_FIXED)
    elif dist_name == 'norm':
        base['mean'] = param(0, DEFAULT_MEAN)
        base['std'] = param(1, DEFAULT_STD)
    elif dist_name == 'expon':
        # scipy.stats.expon(loc, scale): shifted by loc, mean loc + scale.
        loc = param(0, 0.0)
        scale = param(1, _coerce_float(mean_val, DEFAULT_MEAN))
        base['loc'] = loc
        base['mean'] = loc + scale
    elif dist_name == 'uniform':
        # scipy.stats.uniform(loc, scale) spans [loc, loc + scale].
        if len(params) >= 2:
            low = param(0, DEFAULT_MIN)
            base['min'] = low
            base['max'] = low + param(1, DEFAULT_MAX)
        else:
            base['min'] = base['min_value']
            base['max'] = base['max_value']
    elif dist_name == 'lognorm':
        # scipy.stats.lognorm(s, loc, scale).
        base['shape'] = param(0, DEFAULT_LOGNORM_SHAPE)
        base['loc'] = param(1, 0.0)
        base['scale'] = param(2, DEFAULT_LOGNORM_SCALE)
    elif dist_name == 'gamma':
        # scipy.stats.gamma(a, loc, scale). The UI surfaces (Mean, Std) since
        # users rarely think in shape/scale terms.
        shape = param(0, DEFAULT_GAMMA_SHAPE)
        loc = param(1, 0.0)
        scale = param(2, DEFAULT_GAMMA_SCALE)
        base['shape'] = shape
        base['loc'] = loc
        base['scale'] = scale
        base['mean'] = loc + shape * scale
        base['std'] = (shape ** 0.5) * scale
    return base


def normalize_distribution_object(dist_obj: Any, leaf_value: Any = None) -> Any:
    """Bring the ``dist`` of a tree leaf to prosit-pm's shape.

    ``params`` is a list when the leaf still holds what prosit-pm discovered,
    and a dict of UI parameters once the leaf has been opened in the editor.
    Returns the input untouched if it isn't a dict.
    """
    if not isinstance(dist_obj, dict):
        return dist_obj

    dist_name = dist_obj.get('dist_name', 'expon')
    params_raw = dist_obj.get('params', {})

    if isinstance(params_raw, (list, tuple)):
        return _leaf_from_prosit_params(dist_name, list(params_raw), dist_obj, leaf_value)
    return _leaf_from_ui_params(dist_name, params_raw, dist_obj, leaf_value)


def _leaf_from_prosit_params(dist_name, params, dist_obj, leaf_value):
    """Parameters already in prosit-pm's own layout: keep the leaf as it is.

    Only what prosit-pm needs to load the tree is filled in when missing.
    """
    known = dist_name in SUPPORTED_DISTRIBUTIONS
    result = dict(dist_obj)
    result['dist_name'] = dist_name
    if not params:
        if known:
            params, _ = _scipy_params(dist_name, dist_obj, leaf_value)
        else:
            params = [_or(_number(leaf_value), DEFAULT_FIXED)]
    result['params'] = params
    if 'min_value' not in result or 'max_value' not in result:
        low, high = _natural_bounds(dist_name, params) if known else (DEFAULT_MIN, DEFAULT_MAX)
        result.setdefault('min_value', low)
        result.setdefault('max_value', high)
    return result


def _leaf_from_ui_params(dist_name, params_raw, dist_obj, leaf_value):
    """Parameters edited in the tree editor: same conversion as a plain distribution."""
    values = {
        key: dist_obj[key] for key in ('min_value', 'max_value', 'mean_value') if key in dist_obj
    }
    if isinstance(params_raw, dict):
        values.update(params_raw)

    if dist_name in SUPPORTED_DISTRIBUTIONS:
        return distribution_to_prosit(dist_name, values, leaf_value)

    # Unknown family: keep a 'params' list so that prosit-pm can load the tree.
    mean = _or(_first(values, 'mean', 'mean_value'), _or(_number(leaf_value), DEFAULT_MEAN))
    return {
        'dist_name': dist_name,
        'params': [mean],
        'min_value': _or(_first(values, 'min', 'min_value'), DEFAULT_MIN),
        'max_value': _or(_first(values, 'max', 'max_value'), DEFAULT_MAX),
        'mean_value': mean,
    }


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
            dist_in = node.get('dist', default_dist)
            edited_in_ui = isinstance(dist_in, dict) and not isinstance(dist_in.get('params'), (list, tuple))
            dist = normalize_distribution_object(dist_in, leaf_value)
            if isinstance(dist, dict) and edited_in_ui:
                if dist.get('dist_name') == 'fixed':
                    # prosit-pm samples a fixed leaf from the leaf's own value,
                    # not from the distribution: the two must agree, or editing
                    # the fixed value in the UI changes nothing.
                    leaf_value = dist['params'][0]
                elif leaf_value is None:
                    leaf_value = dist.get('mean_value')
            normalized[key] = {'value': leaf_value, 'dist': dist}
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
    """Convert one ``{distribution, parameters}`` UI entry (or a tree) to prosit-pm.

    Execution times, waiting times, inter-arrival times and data attributes all
    flow through this single helper.
    """
    if isinstance(params, dict) and '0' in params:
        return transform_distribution_tree(params)

    dist = params.get('distribution', 'fixed') if isinstance(params, dict) else 'fixed'
    pv = params.get('parameters', {}) if isinstance(params, dict) else {}
    return distribution_to_prosit(dist, pv)


def prosit_entry_to_app(entry: Any) -> Any:
    """Inverse of ``app_entry_to_prosit``: what the UI receives for one entry.

    A decision tree (a dict without ``params``) is shown as it is; a plain
    distribution becomes ``{"distribution": ..., "parameters": {...}}``.
    """
    if not isinstance(entry, dict) or 'params' not in entry:
        return entry
    dist_name = entry.get('dist_name', 'fixed')
    params = entry.get('params') or [DEFAULT_FIXED]
    return {
        'distribution': dist_name,
        'parameters': distribution_from_prosit(
            dist_name,
            params,
            entry.get('min_value', DEFAULT_FIXED),
            entry.get('max_value', DEFAULT_FIXED),
            entry.get('mean_value', params[0]),
        ),
    }


def attribute_entry_from_prosit(stored: Any):
    """A continuous data attribute as prosit-pm stores it -> a distribution entry.

    Since 1.0.2 prosit-pm names the keys of a data attribute ``dist`` / ``min`` /
    ``max`` / ``mean``; older documents use the same names as time distributions.
    Returns ``None`` for anything that is not a continuous attribute.
    """
    if not isinstance(stored, dict) or 'params' not in stored:
        return None
    params = stored.get('params') or [DEFAULT_FIXED]
    return {
        'dist_name': stored.get('dist') or stored.get('dist_name', 'fixed'),
        'params': params,
        'min_value': stored.get('min', stored.get('min_value', DEFAULT_FIXED)),
        'max_value': stored.get('max', stored.get('max_value', DEFAULT_FIXED)),
        'mean_value': stored.get('mean', stored.get('mean_value', params[0])),
    }


def merge_app_entry(stored: Any, app_entry: Any) -> Any:
    """prosit-pm entry to store for ``app_entry``, given what is stored now.

    An entry that comes back exactly as the UI received it was not edited: the
    stored one is kept as it is, to the last bit, instead of being converted
    there and back.
    """
    if stored is not None and app_entry == prosit_entry_to_app(stored):
        return stored
    return app_entry_to_prosit(app_entry)
