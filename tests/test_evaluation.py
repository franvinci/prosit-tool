"""Unit tests for evaluation.py — entropy edge cases and DataFrame side effects."""

import numpy as np
import pandas as pd
import pytest

from evaluation import (
    compute_atd_entropy,
    compute_ctd_entropy,
    compute_etd_entropy,
    compute_handover_error,
    evaluate,
)


def _make_log(rows):
    """Build a DataFrame in XES-style with ISO8601 string timestamps."""
    return pd.DataFrame(rows, columns=[
        'case:concept:name', 'concept:name', 'org:resource',
        'start:timestamp', 'time:timestamp',
    ])


@pytest.fixture
def normal_log():
    return _make_log([
        ('c1', 'A', 'r1', '2024-01-01T08:00:00+00:00', '2024-01-01T08:10:00+00:00'),
        ('c1', 'B', 'r2', '2024-01-01T08:10:00+00:00', '2024-01-01T08:25:00+00:00'),
        ('c2', 'A', 'r1', '2024-01-01T09:00:00+00:00', '2024-01-01T09:05:00+00:00'),
        ('c2', 'B', 'r2', '2024-01-01T09:05:00+00:00', '2024-01-01T09:30:00+00:00'),
        ('c3', 'A', 'r1', '2024-01-01T10:00:00+00:00', '2024-01-01T10:15:00+00:00'),
        ('c3', 'B', 'r2', '2024-01-01T10:15:00+00:00', '2024-01-01T10:40:00+00:00'),
    ])


@pytest.fixture
def single_trace_log():
    return _make_log([
        ('c1', 'A', 'r1', '2024-01-01T08:00:00+00:00', '2024-01-01T08:10:00+00:00'),
        ('c1', 'B', 'r2', '2024-01-01T08:10:00+00:00', '2024-01-01T08:25:00+00:00'),
    ])


def _datetime_log(df):
    """Pre-cast timestamps so the entropy helpers can do timedelta arithmetic."""
    df = df.copy()
    for col in ('start:timestamp', 'time:timestamp'):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


# --- atd_entropy --------------------------------------------------------------


def test_atd_entropy_single_trace_returns_zero(single_trace_log):
    df = _datetime_log(single_trace_log)
    assert compute_atd_entropy(df) == 0.0


def test_atd_entropy_normal_log_finite(normal_log):
    df = _datetime_log(normal_log)
    result = compute_atd_entropy(df)
    assert isinstance(result, float)
    assert np.isfinite(result)
    assert result >= 0.0


# --- ctd_entropy --------------------------------------------------------------


def test_ctd_entropy_single_trace_returns_zero(single_trace_log):
    df = _datetime_log(single_trace_log)
    assert compute_ctd_entropy(df) == 0.0


def test_ctd_entropy_normal_log_finite(normal_log):
    df = _datetime_log(normal_log)
    result = compute_ctd_entropy(df)
    assert isinstance(result, float)
    assert np.isfinite(result)
    assert result >= 0.0


# --- etd_entropy --------------------------------------------------------------


def test_etd_entropy_handles_activity_with_one_event():
    """An activity with a single event should not produce NaN."""
    df = _datetime_log(_make_log([
        ('c1', 'A', 'r1', '2024-01-01T08:00:00+00:00', '2024-01-01T08:10:00+00:00'),
        ('c1', 'B', 'r2', '2024-01-01T08:10:00+00:00', '2024-01-01T08:25:00+00:00'),
        ('c2', 'A', 'r1', '2024-01-01T09:00:00+00:00', '2024-01-01T09:05:00+00:00'),
        # Activity B has only one event (c1) → must not introduce NaN.
        ('c2', 'C', 'r3', '2024-01-01T09:05:00+00:00', '2024-01-01T09:30:00+00:00'),
    ]))
    result = compute_etd_entropy(df)
    assert isinstance(result, float)
    assert np.isfinite(result)


def test_etd_entropy_normal_log_finite(normal_log):
    df = _datetime_log(normal_log)
    result = compute_etd_entropy(df)
    assert isinstance(result, float)
    assert np.isfinite(result)


# --- handover_error -----------------------------------------------------------


def test_handover_error_identical_logs(normal_log):
    err = compute_handover_error(normal_log, normal_log)
    assert err == 0.0


# --- evaluate() does not mutate caller DataFrames (B3 regression) -------------


def test_evaluate_does_not_mutate_input_dataframes(normal_log):
    original = normal_log.copy()
    simulated = normal_log.copy()

    original_start_dtype = original['start:timestamp'].dtype
    simulated_start_dtype = simulated['start:timestamp'].dtype

    # Sanity: input was a string column.
    assert original_start_dtype == object

    evaluate(original, simulated, metrics_labels=['cfld'])

    # After evaluate(), the caller's columns must remain untouched (string).
    assert original['start:timestamp'].dtype == original_start_dtype
    assert simulated['start:timestamp'].dtype == simulated_start_dtype
