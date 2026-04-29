"""Unit tests for the input validators."""

import pytest

from validators import (
    parse_bool,
    validate_attribute_mode,
    validate_grace_period,
    validate_max_depth_tree,
    validate_multitasking_thr,
    validate_noise_threshold,
    validate_num_instances,
    validate_random_state,
)


# --- noise_threshold ---------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (None, 0.2),
    ('', 0.2),
    ('0', 0.0),
    ('0.5', 0.5),
    ('1', 1.0),
])
def test_noise_threshold_accepts_valid(raw, expected):
    val, err = validate_noise_threshold(raw)
    assert err is None
    assert val == expected


@pytest.mark.parametrize("raw", ['-0.1', '1.5', 'abc'])
def test_noise_threshold_rejects_out_of_range(raw):
    val, err = validate_noise_threshold(raw)
    assert err is not None


# --- max_depth_tree ----------------------------------------------------------

def test_max_depth_clamps_above_max():
    val, err = validate_max_depth_tree('99')
    assert err is None
    assert val == 5


def test_max_depth_clamps_negative():
    val, err = validate_max_depth_tree('-2')
    assert err is None
    assert val == 0


def test_max_depth_default_when_missing():
    val, err = validate_max_depth_tree(None)
    assert (val, err) == (0, None)


def test_max_depth_rejects_garbage():
    val, err = validate_max_depth_tree('not-an-int')
    assert err is not None


# --- grace_period ------------------------------------------------------------

def test_grace_period_falls_back_below_min():
    val, err = validate_grace_period('0')
    assert err is None
    assert val == 1000


def test_grace_period_passes_through_large():
    val, err = validate_grace_period('5000')
    assert val == 5000


# --- multitasking_thr --------------------------------------------------------

def test_multitasking_thr_default():
    assert validate_multitasking_thr(None) == (0.05, None)


def test_multitasking_thr_rejects_above_one():
    val, err = validate_multitasking_thr('1.5')
    assert err is not None


# --- random_state ------------------------------------------------------------

def test_random_state_default():
    assert validate_random_state(None) == (72, None)


def test_random_state_accepts_negative():
    val, err = validate_random_state('-1')
    assert (val, err) == (-1, None)


# --- num_instances (strict) --------------------------------------------------

def test_num_instances_default_when_missing():
    assert validate_num_instances(None) == (100, None)


def test_num_instances_rejects_zero():
    val, err = validate_num_instances('0')
    assert val is None
    assert err is not None


def test_num_instances_rejects_above_max():
    val, err = validate_num_instances('99999')
    assert val is None
    assert 'between' in err


def test_num_instances_rejects_garbage():
    val, err = validate_num_instances('lots')
    assert val is None
    assert err is not None


# --- parse_bool --------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ('1', True),
    ('true', True),
    ('TRUE', True),
    ('yes', True),
    ('on', True),
    ('0', False),
    ('false', False),
    ('', False),
    (None, False),
])
def test_parse_bool(raw, expected):
    assert parse_bool(raw) is expected


# --- validate_attribute_mode -------------------------------------------------


def test_attribute_mode_default_when_missing():
    val, err = validate_attribute_mode(None)
    assert val == 'distribution'
    assert err is None


def test_attribute_mode_accepts_distribution():
    assert validate_attribute_mode('distribution') == ('distribution', None)


def test_attribute_mode_accepts_empirical():
    assert validate_attribute_mode('empirical') == ('empirical', None)


def test_attribute_mode_rejects_garbage():
    val, err = validate_attribute_mode('foo')
    assert val == 'distribution'
    assert err is not None
