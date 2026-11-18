"""Unit tests for the input validators."""

import pytest

from datetime import datetime

from prosit_tool.validators import (
    parse_bool,
    validate_attribute_mode,
    validate_discovery_options,
    validate_grace_period,
    validate_max_depth_tree,
    validate_multitasking_thr,
    validate_noise_threshold,
    validate_num_instances,
    validate_random_state,
    validate_run_id,
    validate_start_timestamp,
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

@pytest.mark.parametrize("raw, expected", [('0', 0), ('3', 3), ('5', 5)])
def test_max_depth_accepts_the_supported_range(raw, expected):
    assert validate_max_depth_tree(raw) == (expected, None)


@pytest.mark.parametrize("raw", ['99', '6', '-2'])
def test_max_depth_out_of_range_is_an_error_not_a_silent_clamp(raw):
    val, err = validate_max_depth_tree(raw)
    assert err == 'max_depth_tree must be between 0 and 5'


def test_max_depth_default_when_missing():
    val, err = validate_max_depth_tree(None)
    assert (val, err) == (0, None)


def test_max_depth_rejects_garbage():
    val, err = validate_max_depth_tree('not-an-int')
    assert err is not None


# --- grace_period ------------------------------------------------------------

def test_grace_period_below_min_is_an_error_not_a_silent_default():
    val, err = validate_grace_period('0')
    assert err == 'grace_period must be at least 1'


def test_grace_period_default_when_missing():
    assert validate_grace_period(None) == (1000, None)
    assert validate_grace_period('') == (1000, None)


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


# --- discovery options ---------------------------------------------------------


def test_discovery_options_defaults():
    options, err = validate_discovery_options({})
    assert err is None
    assert options == {
        'max_depth_tree': 0,
        'grace_period': 1000,
        'multitasking_thr': 0.05,
        'random_state': 72,
        'attribute_mode': 'distribution',
        'incremental_discovery': False,
        'enable_multitasking': False,
        'use_workload_features': False,
    }


def test_discovery_options_as_sent_by_the_form():
    options, err = validate_discovery_options({
        'max_depth_tree': '2', 'grace_period': '500', 'multitasking_thr': '0.1', 'random_state': '7',
        'attribute_mode': 'empirical', 'incremental_discovery': '1', 'enable_multitasking': '0',
        'use_workload_features': 'true',
    })
    assert err is None
    assert options == {
        'max_depth_tree': 2, 'grace_period': 500, 'multitasking_thr': 0.1, 'random_state': 7,
        'attribute_mode': 'empirical', 'incremental_discovery': True, 'enable_multitasking': False,
        'use_workload_features': True,
    }


@pytest.mark.parametrize("args, message", [
    ({'max_depth_tree': '9'}, 'max_depth_tree must be between 0 and 5'),
    ({'grace_period': 'soon'}, "grace_period: expected an integer, got 'soon'"),
    ({'multitasking_thr': '2'}, 'multitasking_thr must be between 0 and 1'),
    ({'attribute_mode': 'exact'}, "attribute_mode must be one of ('distribution', 'empirical')"),
])
def test_discovery_options_name_the_invalid_one(args, message):
    assert validate_discovery_options(args) == ({}, message)


# --- run_id --------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [(None, None), ('', None), (7, 7), ('7', 7)])
def test_run_id_accepts(raw, expected):
    assert validate_run_id(raw) == (expected, None)


@pytest.mark.parametrize("raw", ['latest', '7.5', True, [7]])
def test_run_id_rejects(raw):
    val, err = validate_run_id(raw)
    assert val is None and 'run_id must be an integer' in err


# --- start_timestamp -----------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    (None, None),
    ('', None),
    ('2024-03-04T10:00', datetime(2024, 3, 4, 10, 0)),
    ('2024-03-04 10:00:30', datetime(2024, 3, 4, 10, 0, 30)),
    # An offset is dropped, not converted: the calendars have no time zone.
    ('2024-03-04T10:00:00Z', datetime(2024, 3, 4, 10, 0)),
    ('2024-03-04T10:00:00+05:00', datetime(2024, 3, 4, 10, 0)),
])
def test_start_timestamp_accepts(raw, expected):
    assert validate_start_timestamp(raw) == (expected, None)


@pytest.mark.parametrize("raw", ['monday', '04/03/2024', 20240304, ['2024-03-04']])
def test_start_timestamp_rejects(raw):
    val, err = validate_start_timestamp(raw)
    assert val is None and 'start_timestamp must be an ISO 8601 date and time' in err
