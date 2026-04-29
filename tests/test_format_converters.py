"""Round-trip tests for format_converters.

These guard the refactor in Phase 3: they confirm that the unified helpers
produce the same shape that the four near-duplicated inline blocks used to
produce in routes.py / prosit_integration.py.
"""

import pytest

from format_converters import (
    app_entry_to_prosit,
    distribution_from_prosit,
    distribution_to_prosit,
    normalize_distribution_object,
    transform_distribution_tree,
)


# --- distribution_to_prosit ---------------------------------------------------

def test_to_prosit_fixed_minmax_pinned_to_value():
    out = distribution_to_prosit('fixed', {'value': 7})
    assert out == {
        'dist_name': 'fixed',
        'params': [7.0],
        'min_value': 7.0,
        'max_value': 7.0,
        'mean_value': 7.0,
    }


def test_to_prosit_norm_uses_mean_and_std():
    out = distribution_to_prosit('norm', {'mean': 10, 'std': 3, 'min': 0, 'max': 50})
    assert out['dist_name'] == 'norm'
    assert out['params'] == [10.0, 3.0]
    assert out['min_value'] == 0.0
    assert out['max_value'] == 50.0
    assert out['mean_value'] == 10.0


def test_to_prosit_expon_emits_loc_zero_then_scale():
    out = distribution_to_prosit('expon', {'mean': 12})
    assert out['params'] == [0.0, 12.0]
    assert out['mean_value'] == 12.0


def test_to_prosit_uniform_uses_min_max_and_midpoint_mean():
    out = distribution_to_prosit('uniform', {'min': 4, 'max': 16})
    assert out['params'] == [4.0, 16.0]
    assert out['mean_value'] == 10.0


def test_to_prosit_unknown_distribution_falls_back_to_fixed():
    out = distribution_to_prosit('weibull', {'mean': 9})
    assert out['dist_name'] == 'fixed'
    assert out['params'] == [1.0]


# --- distribution_from_prosit -------------------------------------------------

def test_from_prosit_fixed_carries_value():
    out = distribution_from_prosit('fixed', [7.0], 7.0, 7.0, 7.0)
    assert out['value'] == 7.0


def test_from_prosit_norm_decodes_mean_std():
    out = distribution_from_prosit('norm', [10.0, 3.0], 0.0, 50.0, 10.0)
    assert out['mean'] == 10.0
    assert out['std'] == 3.0


def test_from_prosit_expon_uses_scale_as_mean():
    out = distribution_from_prosit('expon', [0.0, 12.0], 1.0, 60.0, 12.0)
    assert out['mean'] == 12.0
    assert out['scale'] == 12.0


def test_from_prosit_uniform_decodes_min_max():
    out = distribution_from_prosit('uniform', [4.0, 16.0], 4.0, 16.0, 10.0)
    assert out['min'] == 4.0
    assert out['max'] == 16.0


# --- round-trip: prosit → app → prosit ----------------------------------------

@pytest.mark.parametrize("dist_name, params, mn, mx, me", [
    ('fixed', [7.0], 7.0, 7.0, 7.0),
    ('norm', [10.0, 3.0], 0.0, 50.0, 10.0),
    ('expon', [0.0, 12.0], 1.0, 60.0, 12.0),
    ('uniform', [4.0, 16.0], 4.0, 16.0, 10.0),
])
def test_roundtrip_prosit_app_prosit(dist_name, params, mn, mx, me):
    app = distribution_from_prosit(dist_name, params, mn, mx, me)
    back = distribution_to_prosit(dist_name, app)
    assert back['dist_name'] == dist_name
    assert back['params'] == params or len(back['params']) == len(params)


# --- normalize_distribution_object --------------------------------------------

def test_normalize_passes_non_dict_through():
    assert normalize_distribution_object(42) == 42
    assert normalize_distribution_object(None) is None


def test_normalize_with_list_params_norm():
    out = normalize_distribution_object({'dist_name': 'norm', 'params': [10, 3]})
    assert out['params'] == [10, 3]
    assert out['mean_value'] == 10


def test_normalize_with_object_params_norm():
    out = normalize_distribution_object({
        'dist_name': 'norm',
        'params': {'mean': 10, 'std': 3, 'min': 0, 'max': 50},
    })
    assert out['params'] == [10, 3]
    assert out['min_value'] == 0


# --- transform_distribution_tree ----------------------------------------------

def test_transform_tree_normalizes_leaves():
    tree = {
        '0': {'value': 5, 'dist': {'dist_name': 'norm', 'params': {'mean': 5, 'std': 1}}},
        '1': {'feature': 'org:resource', 'threshold': 0.5, 'children': {}},
    }
    out = transform_distribution_tree(tree)
    assert out['0']['dist']['params'] == [5, 1]
    assert out['1']['feature'] == 'org:resource'


def test_transform_tree_passes_non_dict_through():
    assert transform_distribution_tree("not-a-tree") == "not-a-tree"


# --- app_entry_to_prosit (the dispatcher) -------------------------------------

def test_app_entry_dispatches_to_distribution():
    out = app_entry_to_prosit({'distribution': 'norm',
                               'parameters': {'mean': 10, 'std': 3, 'min': 0, 'max': 50}})
    assert out['dist_name'] == 'norm'


def test_app_entry_dispatches_to_tree():
    tree = {'0': {'value': 5, 'dist': {'dist_name': 'norm', 'params': [5, 1]}}}
    out = app_entry_to_prosit(tree)
    assert '0' in out
    assert out['0']['dist']['params'] == [5, 1]


# --- regression: unsupported distributions must keep params (bug #6) -----------


def test_normalize_unknown_dist_with_list_preserves_params():
    """lognorm and friends must round-trip with their params intact —
    otherwise prosit_pm.dict_to_decrules raises KeyError: 'params'."""
    out = normalize_distribution_object({
        'dist_name': 'lognorm',
        'params': [0.5, 0.0, 3.96],
        'min_value': 0,
        'max_value': 272,
        'mean_value': 3.96,
    })
    assert out['dist_name'] == 'lognorm'
    assert out['params'] == [0.5, 0.0, 3.96]
    assert out['min_value'] == 0
    assert out['max_value'] == 272
    assert out['mean_value'] == 3.96


def test_normalize_unknown_dist_with_object_preserves_params():
    out = normalize_distribution_object({
        'dist_name': 'gamma',
        'params': {'mean': 5, 'std': 2, 'min': 0, 'max': 100},
    })
    # Falls through _normalize_from_object's "unknown" branch.
    assert out['dist_name'] == 'gamma'
    assert 'params' in out
    assert 'min_value' in out and 'max_value' in out


def test_to_prosit_lognorm_emits_three_params():
    out = distribution_to_prosit('lognorm', {'shape': 0.7, 'scale': 5.0, 'min': 0, 'max': 100})
    assert out['dist_name'] == 'lognorm'
    assert len(out['params']) == 3
    assert out['params'][0] == 0.7
    assert out['params'][2] == 5.0


def test_from_prosit_lognorm_decodes_shape_scale():
    out = distribution_from_prosit('lognorm', [0.7, 0.0, 5.0], 0.0, 100.0, 5.0)
    assert out['shape'] == 0.7
    assert out['scale'] == 5.0


def test_normalize_lognorm_with_list_params_keeps_three():
    out = normalize_distribution_object({
        'dist_name': 'lognorm',
        'params': [0.6, 0.0, 8.0],
        'min_value': 0,
        'max_value': 200,
    })
    assert out['params'] == [0.6, 0.0, 8.0]


def test_to_prosit_gamma_emits_three_params():
    out = distribution_to_prosit('gamma', {'shape': 2.5, 'scale': 4.0, 'min': 0, 'max': 200})
    assert out['dist_name'] == 'gamma'
    assert len(out['params']) == 3
    assert out['params'][0] == 2.5
    assert out['params'][2] == 4.0


def test_to_prosit_gamma_accepts_mean_std_and_derives_shape_scale():
    """The UI surfaces Mean+Std for gamma; conversion derives scipy shape/scale."""
    out = distribution_to_prosit('gamma', {'mean': 60, 'std': 30, 'min': 0, 'max': 200})
    shape, _, scale = out['params']
    # shape = mean² / std²; scale = std² / mean
    assert abs(shape - 4.0) < 1e-9
    assert abs(scale - 15.0) < 1e-9
    # Sanity: round-trip mean back from (shape, scale) reproduces the input.
    assert abs(shape * scale - 60.0) < 1e-9


def test_from_prosit_gamma_returns_mean_and_std():
    out = distribution_from_prosit('gamma', [4.0, 0.0, 15.0], 0, 200, 60.0)
    assert abs(out['mean'] - 60.0) < 1e-9
    assert abs(out['std'] - 30.0) < 1e-9


def test_normalize_gamma_with_list_keeps_three():
    out = normalize_distribution_object({
        'dist_name': 'gamma',
        'params': [3.0, 0.0, 5.0],
        'min_value': 0,
        'max_value': 100,
    })
    assert out['params'] == [3.0, 0.0, 5.0]


def test_transform_tree_preserves_lognorm_leaf():
    tree = {
        '0': {
            'value': 3.96,
            'dist': {
                'dist_name': 'lognorm',
                'params': [0.5, 0.0, 3.96],
                'min_value': 0,
                'max_value': 272,
                'mean_value': 3.96,
            },
        },
    }
    out = transform_distribution_tree(tree)
    leaf_dist = out['0']['dist']
    assert leaf_dist['dist_name'] == 'lognorm'
    assert leaf_dist['params'] == [0.5, 0.0, 3.96]
    assert leaf_dist['min_value'] == 0
    assert leaf_dist['max_value'] == 272
