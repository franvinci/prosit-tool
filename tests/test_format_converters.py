"""Distribution conversions between the UI shape and prosit-pm's JSON shape.

The property that matters: ``prosit -> UI -> prosit`` returns what it started
from. The UI sends every distribution of a scenario back on each save, so a
conversion that loses anything silently alters distributions the user never
touched.
"""

import numpy as np
import pytest
import scipy.stats

from prosit.utils.distribution_utils import sampling_from_dist

from prosit_tool.format_converters import (
    app_entry_to_prosit,
    attribute_entry_from_prosit,
    distribution_from_prosit,
    distribution_to_prosit,
    merge_app_entry,
    normalize_distribution_object,
    prosit_entry_to_app,
    transform_distribution_tree,
)


def _entry(dist_name, params, min_value, max_value, mean_value):
    return {
        'dist_name': dist_name,
        'params': list(params),
        'min_value': min_value,
        'max_value': max_value,
        'mean_value': mean_value,
    }


# Entries with the shape scipy really fits: shifted exponentials, uniforms that
# do not start at zero, three-parameter lognormals.
STORED_ENTRIES = [
    _entry('fixed', [7.0], 7.0, 7.0, 7.0),
    _entry('norm', [10.0, 3.0], 0.0, 50.0, 10.0),
    _entry('expon', [0.0, 12.0], 0.0, 60.0, 12.0),
    _entry('expon', [20.002, 14.588], 20.002, 148.974, 34.59),
    _entry('uniform', [0.0, 16.0], 0.0, 16.0, 8.0),
    _entry('uniform', [10.004, 19.988], 10.004, 29.992, 19.998),
    _entry('lognorm', [0.7, 1.5, 5.0], 2.0, 100.0, 7.9),
    _entry('gamma', [4.0, 0.0, 15.0], 0.0, 200.0, 60.0),
    _entry('gamma', [2.5, 3.0, 4.0], 3.0, 80.0, 13.0),
]
IDS = [f"{e['dist_name']}{e['params']}" for e in STORED_ENTRIES]


def _approx_entry(entry):
    return {
        'dist_name': entry['dist_name'],
        'params': pytest.approx(entry['params'], rel=1e-12, abs=1e-12),
        'min_value': pytest.approx(entry['min_value'], rel=1e-12, abs=1e-12),
        'max_value': pytest.approx(entry['max_value'], rel=1e-12, abs=1e-12),
        # mean_value is not compared: it is the mean of the *distribution*, not
        # a copy of the mean of the data it was fitted on, and prosit-pm only
        # reads it for the "fixed" family (covered separately).
    }


def _without_mean(entry):
    return {k: v for k, v in entry.items() if k != 'mean_value'}


# --- round trip -------------------------------------------------------------------

@pytest.mark.parametrize("stored", STORED_ENTRIES, ids=IDS)
def test_conversion_is_lossless(stored):
    """prosit -> UI -> prosit gives back the same distribution."""
    shown = prosit_entry_to_app(stored)
    back = app_entry_to_prosit(shown)

    assert _without_mean(back) == _approx_entry(stored)


@pytest.mark.parametrize("stored", STORED_ENTRIES, ids=IDS)
def test_unedited_entry_is_kept_to_the_last_bit(stored):
    """What comes back as it was sent is not converted at all."""
    shown = prosit_entry_to_app(stored)

    assert merge_app_entry(stored, shown) is stored


@pytest.mark.parametrize("stored", [e for e in STORED_ENTRIES if e['dist_name'] != 'fixed'],
                         ids=[i for i in IDS if not i.startswith('fixed')])
def test_round_trip_samples_the_same_values(stored):
    """The simulator draws the same numbers before and after a round trip."""
    back = app_entry_to_prosit(prosit_entry_to_app(stored))
    dist = getattr(scipy.stats, stored['dist_name'])

    def sample(entry):
        np.random.seed(7)
        return sampling_from_dist(dist, tuple(entry['params']), entry['min_value'],
                                  entry['max_value'], entry['mean_value'], 5000)

    np.testing.assert_allclose(sample(back), sample(stored), rtol=1e-9, atol=1e-9)


def test_fixed_round_trip_keeps_the_value_the_simulator_uses():
    stored = _entry('fixed', [7.5], 7.5, 7.5, 7.5)
    back = app_entry_to_prosit(prosit_entry_to_app(stored))
    assert back == stored


# --- what the UI shows --------------------------------------------------------------

def test_uniform_is_shown_with_its_real_bounds():
    """scipy's uniform(loc, scale) spans [loc, loc + scale], not [loc, scale]."""
    shown = distribution_from_prosit('uniform', [10.0, 20.0], 10.0, 30.0, 20.0)
    assert shown['min'] == 10.0
    assert shown['max'] == 30.0


def test_exponential_is_shown_with_its_real_mean_and_shift():
    shown = distribution_from_prosit('expon', [20.0, 15.0], 20.0, 150.0, 35.0)
    assert shown['mean'] == 35.0
    assert shown['loc'] == 20.0


def test_gamma_is_shown_with_mean_and_std():
    shown = distribution_from_prosit('gamma', [4.0, 0.0, 15.0], 0, 200, 60.0)
    assert shown['mean'] == pytest.approx(60.0)
    assert shown['std'] == pytest.approx(30.0)

    shifted = distribution_from_prosit('gamma', [4.0, 10.0, 15.0], 10, 200, 70.0)
    assert shifted['mean'] == pytest.approx(70.0)
    assert shifted['loc'] == 10.0


def test_from_prosit_fixed_norm_lognorm():
    assert distribution_from_prosit('fixed', [7.0], 7.0, 7.0, 7.0)['value'] == 7.0

    norm = distribution_from_prosit('norm', [10.0, 3.0], 0.0, 50.0, 10.0)
    assert (norm['mean'], norm['std']) == (10.0, 3.0)

    lognorm = distribution_from_prosit('lognorm', [0.7, 0.0, 5.0], 0.0, 100.0, 5.0)
    assert (lognorm['shape'], lognorm['loc'], lognorm['scale']) == (0.7, 0.0, 5.0)


# --- what an edit in the UI produces ------------------------------------------------

def test_to_prosit_fixed_minmax_pinned_to_value():
    assert distribution_to_prosit('fixed', {'value': 7}) == _entry('fixed', [7.0], 7.0, 7.0, 7.0)


def test_to_prosit_norm_uses_mean_and_std():
    out = distribution_to_prosit('norm', {'mean': 10, 'std': 3, 'min': 0, 'max': 50})
    assert out == _entry('norm', [10.0, 3.0], 0.0, 50.0, 10.0)


def test_editing_the_bounds_of_a_uniform():
    shown = distribution_from_prosit('uniform', [10.0, 20.0], 10.0, 30.0, 20.0)
    shown['max'] = 50.0  # the user widens the range to [10, 50]

    out = distribution_to_prosit('uniform', shown)

    assert out == _entry('uniform', [10.0, 40.0], 10.0, 50.0, 30.0)
    np.random.seed(1)
    drawn = sampling_from_dist(scipy.stats.uniform, tuple(out['params']), out['min_value'],
                               out['max_value'], out['mean_value'], 20000)
    assert drawn.min() >= 10.0 and drawn.max() <= 50.0
    assert drawn.mean() == pytest.approx(30.0, abs=0.5)
    # No pile-up at the upper bound (the old conversion clipped half the mass there).
    assert (drawn >= 49.99).mean() < 0.01


def test_uniform_with_swapped_bounds_is_put_in_order():
    out = distribution_to_prosit('uniform', {'min': 16, 'max': 4})
    assert out['params'] == [4.0, 12.0]
    assert (out['min_value'], out['max_value']) == (4.0, 16.0)


def test_editing_the_mean_of_a_shifted_exponential_keeps_the_shift():
    shown = distribution_from_prosit('expon', [20.0, 15.0], 20.0, 150.0, 35.0)
    shown['mean'] = 50.0

    out = distribution_to_prosit('expon', shown)

    assert out['params'] == [20.0, 30.0]
    assert out['mean_value'] == 50.0


def test_exponential_mean_below_the_shift_becomes_a_plain_exponential():
    shown = distribution_from_prosit('expon', [20.0, 15.0], 20.0, 150.0, 35.0)
    shown['mean'] = 12.0

    assert distribution_to_prosit('expon', shown)['params'] == [0.0, 12.0]


def test_plain_exponential_from_a_mean():
    out = distribution_to_prosit('expon', {'mean': 12})
    assert out['params'] == [0.0, 12.0]
    assert out['mean_value'] == 12.0


def test_to_prosit_lognorm_emits_three_params():
    out = distribution_to_prosit('lognorm', {'shape': 0.7, 'scale': 5.0, 'min': 0, 'max': 100})
    assert out['dist_name'] == 'lognorm'
    assert out['params'] == [0.7, 0.0, 5.0]
    assert (out['min_value'], out['max_value']) == (0.0, 100.0)


def test_to_prosit_gamma_from_shape_and_scale():
    out = distribution_to_prosit('gamma', {'shape': 2.5, 'scale': 4.0, 'min': 0, 'max': 200})
    assert out['params'] == [2.5, 0.0, 4.0]


def test_to_prosit_gamma_accepts_mean_std_and_derives_shape_scale():
    """The UI surfaces Mean+Std for gamma; conversion derives scipy shape/scale."""
    out = distribution_to_prosit('gamma', {'mean': 60, 'std': 30, 'min': 0, 'max': 200})
    shape, loc, scale = out['params']
    assert shape == pytest.approx(4.0)
    assert scale == pytest.approx(15.0)
    assert loc == 0.0
    assert out['mean_value'] == pytest.approx(60.0)


def test_to_prosit_unknown_distribution_falls_back_to_fixed():
    out = distribution_to_prosit('weibull', {'mean': 9})
    assert out['dist_name'] == 'fixed'
    assert out['params'] == [1.0]


@pytest.mark.parametrize("dist_name, values, expected_mean", [
    ('norm', {'mean': 120, 'std': 30}, 120.0),
    ('expon', {'mean': 120}, 120.0),
    ('gamma', {'mean': 60, 'std': 30}, 60.0),
    ('lognorm', {'shape': 0.5, 'loc': 0, 'scale': 60}, 60 * np.exp(0.125)),
])
def test_missing_bounds_do_not_clip_the_distribution(dist_name, values, expected_mean):
    """Right after the user picks another family the UI sends no min/max.

    The conversion used to fill in [1, 60], which turned e.g. a Normal(120, 30)
    into a constant 60.
    """
    out = distribution_to_prosit(dist_name, values)

    np.random.seed(3)
    drawn = sampling_from_dist(getattr(scipy.stats, dist_name), tuple(out['params']),
                               out['min_value'], out['max_value'], out['mean_value'], 40000)
    assert drawn.mean() == pytest.approx(expected_mean, rel=0.03)
    at_a_bound = ((drawn <= out['min_value']) | (drawn >= out['max_value'])).mean()
    assert at_a_bound < 0.005


def test_given_bounds_are_respected_and_ordered():
    out = distribution_to_prosit('norm', {'mean': 10, 'std': 3, 'min': 50, 'max': 0})
    assert (out['min_value'], out['max_value']) == (0.0, 50.0)

    # The short keys the user edits win over the ones received from the server.
    out = distribution_to_prosit('norm', {'mean': 10, 'std': 3, 'min_value': 0, 'max_value': 50, 'max': 30})
    assert (out['min_value'], out['max_value']) == (0.0, 30.0)


@pytest.mark.parametrize("junk", [None, 'abc', float('nan'), float('inf'), True, [1], {}])
def test_values_that_are_not_numbers_are_ignored(junk):
    out = distribution_to_prosit('norm', {'mean': junk, 'std': junk, 'min': junk, 'max': junk})
    assert out['params'] == [15.0, 5.0]
    assert all(np.isfinite([out['min_value'], out['max_value'], out['mean_value']]))


# --- entries ----------------------------------------------------------------------

def test_edited_entry_is_converted():
    stored = _entry('norm', [10.0, 3.0], 0.0, 50.0, 10.0)
    shown = prosit_entry_to_app(stored)
    shown['parameters']['mean'] = 12.0

    merged = merge_app_entry(stored, shown)

    assert merged is not stored
    assert merged['params'] == [12.0, 3.0]
    assert stored['params'] == [10.0, 3.0]  # the stored entry is not mutated


def test_entry_without_a_stored_counterpart_is_converted():
    out = merge_app_entry(None, {'distribution': 'expon', 'parameters': {'mean': 8}})
    assert out['params'] == [0.0, 8.0]


def test_app_entry_dispatches_to_distribution():
    out = app_entry_to_prosit({'distribution': 'norm',
                               'parameters': {'mean': 10, 'std': 3, 'min': 0, 'max': 50}})
    assert out['dist_name'] == 'norm'


def test_trees_are_shown_as_they_are():
    tree = {'0': {'value': 5, 'dist': {'dist_name': 'norm', 'params': [5, 1], 'min_value': 0, 'max_value': 9}}}
    assert prosit_entry_to_app(tree) is tree
    assert prosit_entry_to_app(0.25) == 0.25


def test_attribute_entry_reads_both_key_spellings():
    current = attribute_entry_from_prosit(
        {'type': 'continuous', 'dist': 'norm', 'params': [5.0, 1.0], 'min': 0.0, 'max': 9.0, 'mean': 5.0})
    legacy = attribute_entry_from_prosit(
        {'dist_name': 'norm', 'params': [5.0, 1.0], 'min_value': 0.0, 'max_value': 9.0, 'mean_value': 5.0})

    assert current == legacy == _entry('norm', [5.0, 1.0], 0.0, 9.0, 5.0)
    assert attribute_entry_from_prosit({'type': 'categorical', 'values': {'a': 1.0}}) is None
    assert attribute_entry_from_prosit('not-a-dict') is None


# --- tree leaves --------------------------------------------------------------------

def test_normalize_passes_non_dict_through():
    assert normalize_distribution_object(42) == 42
    assert normalize_distribution_object(None) is None


@pytest.mark.parametrize("stored", STORED_ENTRIES, ids=IDS)
def test_leaf_never_opened_in_the_editor_is_untouched(stored):
    """A leaf that still holds prosit-pm's parameter list is passed through."""
    leaf_dist = {k: stored[k] for k in ('dist_name', 'params', 'min_value', 'max_value')}

    assert normalize_distribution_object(dict(leaf_dist), leaf_value=stored['mean_value']) == leaf_dist


def test_leaf_with_list_params_gets_only_the_missing_bounds():
    out = normalize_distribution_object({'dist_name': 'norm', 'params': [10, 3]})
    assert out['params'] == [10, 3]
    assert out['min_value'] < 10 - 2 * 3 and out['max_value'] > 10 + 2 * 3

    out = normalize_distribution_object({'dist_name': 'uniform', 'params': [10, 20]})
    assert (out['min_value'], out['max_value']) == (10, 30)


# What the tree editor of the UI turns a parameter list into when a leaf is
# opened (see arrayToObject in the template). Opening a leaf without editing it
# must store the same distribution.
LEAF_AS_EDITED = {
    'fixed': lambda p, value: {'value': value},
    'norm': lambda p, value: {'mean': p[0], 'std': p[1]},
    'expon': lambda p, value: {'mean': p[0] + p[1], 'loc': p[0]},
    'uniform': lambda p, value: {'min': p[0], 'max': p[0] + p[1]},
    'lognorm': lambda p, value: {'shape': p[0], 'loc': p[1], 'scale': p[2]},
    'gamma': lambda p, value: {'mean': p[1] + p[0] * p[2], 'std': (p[0] ** 0.5) * p[2], 'loc': p[1]},
}


@pytest.mark.parametrize("stored", STORED_ENTRIES, ids=IDS)
def test_leaf_opened_but_not_edited_is_the_same_distribution(stored):
    name = stored['dist_name']
    leaf = {
        'value': stored['mean_value'],
        'dist': {
            'dist_name': name,
            'params': LEAF_AS_EDITED[name](stored['params'], stored['mean_value']),
            'min_value': stored['min_value'],
            'max_value': stored['max_value'],
        },
    }

    out = transform_distribution_tree({'0': leaf})['0']

    assert _without_mean(out['dist']) == _approx_entry(stored)
    assert out['value'] == stored['mean_value']


def test_editing_a_fixed_leaf_changes_the_value_the_simulator_samples():
    """prosit-pm samples a fixed leaf from the leaf's ``value``, not from ``dist``."""
    tree = {
        '0': {'feature': 'A', 'threshold': 0.5, 'children': {'true': 1, 'false': 2}},
        '1': {'value': 5.0, 'dist': {'dist_name': 'fixed', 'params': {'value': 42.0}, 'min_value': 42.0, 'max_value': 42.0}},
        '2': {'value': 9.0, 'dist': {'dist_name': 'fixed', 'params': [9.0], 'min_value': 9.0, 'max_value': 9.0}},
    }

    out = transform_distribution_tree(tree)

    assert out['1']['value'] == 42.0
    assert out['1']['dist']['params'] == [42.0]
    # The leaf that was not opened keeps the value it had.
    assert out['2'] == tree['2']
    assert out['0'] == tree['0']


def test_untouched_fixed_leaf_keeps_its_own_value():
    """The value of a discovered leaf is rounded differently from its params."""
    leaf = {'value': 12.345, 'dist': {'dist_name': 'fixed', 'params': [12.3449987], 'min_value': 12.3449987, 'max_value': 12.3449987}}
    assert transform_distribution_tree({'0': leaf})['0'] == leaf


def test_leaf_without_value_gets_the_mean_of_its_edited_distribution():
    tree = {'0': {'value': None, 'dist': {'dist_name': 'norm', 'params': {'mean': 8, 'std': 2}}}}
    assert transform_distribution_tree(tree)['0']['value'] == 8.0


def test_transform_tree_normalizes_leaves_and_keeps_splits():
    tree = {
        '0': {'value': 5, 'dist': {'dist_name': 'norm', 'params': {'mean': 5, 'std': 1}}},
        '1': {'feature': 'org:resource', 'threshold': 0.5, 'children': {}},
    }
    out = transform_distribution_tree(tree)
    assert out['0']['dist']['params'] == [5.0, 1.0]
    assert out['1']['feature'] == 'org:resource'


def test_transform_tree_passes_non_dict_through():
    assert transform_distribution_tree("not-a-tree") == "not-a-tree"


def test_app_entry_dispatches_to_tree():
    tree = {'0': {'value': 5, 'dist': {'dist_name': 'norm', 'params': [5, 1]}}}
    out = app_entry_to_prosit(tree)
    assert '0' in out
    assert out['0']['dist']['params'] == [5, 1]


def test_leaf_of_an_unknown_family_keeps_its_params():
    """Otherwise prosit-pm cannot load the tree (KeyError: 'params')."""
    dist = {'dist_name': 'beta', 'params': [0.5, 0.0, 3.96], 'min_value': 0, 'max_value': 272, 'mean_value': 3.96}
    assert normalize_distribution_object(dict(dist)) == dist

    edited = normalize_distribution_object({'dist_name': 'beta', 'params': {'mean': 5, 'min': 0, 'max': 100}})
    assert edited['dist_name'] == 'beta'
    assert edited['params'] == [5.0]
    assert (edited['min_value'], edited['max_value']) == (0.0, 100.0)
