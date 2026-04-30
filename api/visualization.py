"""Visualization endpoints: per-session activity/resource lookup and chart rendering."""

import os
import logging
from collections import OrderedDict

import numpy as np
import pandas as pd
import pm4py
from pm4py.visualization.dfg.variants import performance as dfg_perf_visualizer

from flask import Blueprint, request, jsonify

from app import app
from models import SimulationRun, SimulationSession

from ._decorators import handle_api_errors

logger = logging.getLogger(__name__)
bp = Blueprint('visualization', __name__)


WEEKDAY_LABELS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

_UNIT_FACTORS = {'sec': 1, 'min': 60, 'hour': 3600, 'day': 86400}
_UNIT_LABELS = {'sec': 'seconds', 'min': 'minutes', 'hour': 'hours', 'day': 'days'}

# In-process caches. Keyed by (filepath, mtime) so a fresh simulation that
# overwrites/changes the file invalidates the cache automatically.
_DF_CACHE: "OrderedDict[tuple[str, float], pd.DataFrame]" = OrderedDict()
_SVG_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_DF_CACHE_MAX = 4
_SVG_CACHE_MAX = 64


def _to_unit(seconds_series, unit):
    """Convert a pandas series of seconds to the requested unit."""
    factor = _UNIT_FACTORS.get(unit, 60)
    return seconds_series / factor


def _unit_label(unit):
    return _UNIT_LABELS.get(unit, 'minutes')


def _resolve_run_for_session(session, run_id):
    """Return the SimulationRun whose simulation log to read.

    With no run_id, falls back to the most recently simulated run for the
    session, or the baseline if none has been simulated yet.
    """
    if run_id is not None:
        run = SimulationRun.query.filter_by(id=int(run_id), session_id=session.id).first()
        return run
    runs_with_logs = [r for r in session.runs if r.simulation_df_filename]
    if runs_with_logs:
        runs_with_logs.sort(key=lambda r: (r.last_run_at or r.created_at), reverse=True)
        return runs_with_logs[0]
    return session.get_baseline_run()


def _load_simulation_df(session, run_id=None):
    """Load the saved simulation CSV for the requested run (or baseline)."""
    run = _resolve_run_for_session(session, run_id)
    sim_log_filename = run.simulation_df_filename if run else None
    if not sim_log_filename:
        return None, ('Simulated log file not found.', 404)

    sim_log_filepath = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), sim_log_filename)
    if not os.path.exists(sim_log_filepath):
        return None, ('Simulated log file not found on server.', 404)

    mtime = os.path.getmtime(sim_log_filepath)
    cache_key = (sim_log_filepath, mtime)
    cached = _DF_CACHE.get(cache_key)
    if cached is not None:
        _DF_CACHE.move_to_end(cache_key)
        return cached, None

    df = pd.read_csv(sim_log_filepath)
    for col in ('start:timestamp', 'time:timestamp', 'enabled:timestamp'):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)

    _DF_CACHE[cache_key] = df
    while len(_DF_CACHE) > _DF_CACHE_MAX:
        _DF_CACHE.popitem(last=False)
    return df, None


def _svg_cache_get(session, viz_type, params, run_id=None):
    """Return cached visualization payload, or None.

    Cache key includes the simulation file's mtime, so a new simulation
    automatically invalidates entries for that run.
    """
    run = _resolve_run_for_session(session, run_id)
    sim_log_filename = run.simulation_df_filename if run else None
    if not sim_log_filename:
        return None
    sim_log_filepath = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), sim_log_filename)
    if not os.path.exists(sim_log_filepath):
        return None
    mtime = os.path.getmtime(sim_log_filepath)
    key = (session.id, run.id if run else None, viz_type, tuple(sorted(params.items())), mtime)
    payload = _SVG_CACHE.get(key)
    if payload is not None:
        _SVG_CACHE.move_to_end(key)
    return payload


def _svg_cache_set(session, viz_type, params, payload, run_id=None):
    run = _resolve_run_for_session(session, run_id)
    sim_log_filename = run.simulation_df_filename if run else None
    if not sim_log_filename:
        return
    sim_log_filepath = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), sim_log_filename)
    if not os.path.exists(sim_log_filepath):
        return
    mtime = os.path.getmtime(sim_log_filepath)
    key = (session.id, run.id if run else None, viz_type, tuple(sorted(params.items())), mtime)
    _SVG_CACHE[key] = payload
    while len(_SVG_CACHE) > _SVG_CACHE_MAX:
        _SVG_CACHE.popitem(last=False)


def _read_run_id():
    raw = request.args.get('run_id')
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@bp.route('/api/get_activities_and_resources/<int:session_id>')
@handle_api_errors('Failed to get data')
def get_activities_and_resources(session_id):
    """List all activities and resources from the saved simulation log."""
    session = SimulationSession.query.get_or_404(session_id)
    df, err = _load_simulation_df(session, run_id=_read_run_id())
    if err:
        msg, code = err
        return jsonify({'error': msg}), code

    activities = sorted(df['concept:name'].unique().tolist())
    resources = sorted(df['org:resource'].dropna().unique().tolist())
    return jsonify({'success': True, 'activities': activities, 'resources': resources})


@bp.route('/api/get_visualization/<int:session_id>/<visualization_type>')
@handle_api_errors('Failed to generate visualization')
def get_visualization(session_id, visualization_type):
    """Generate and return a specific visualization from the simulated log."""
    session = SimulationSession.query.get_or_404(session_id)
    run_id = _read_run_id()

    unit = request.args.get('unit', 'min')
    if unit not in _UNIT_FACTORS:
        unit = 'min'
    aggregation = request.args.get('aggregation', 'median')
    resource_arg = request.args.get('resource') or ''
    activity_arg = request.args.get('activity') or ''

    cache_params = {
        'process_map': {'aggregation': aggregation},
        'case_duration_dist': {'unit': unit},
        'resource_heatmap': {'resource': resource_arg},
        'activity_duration_boxplot': {'activity': activity_arg, 'unit': unit},
        'waiting_time_dist': {'activity': activity_arg, 'resource': resource_arg, 'unit': unit},
    }.get(visualization_type)

    if cache_params is not None:
        cached = _svg_cache_get(session, visualization_type, cache_params, run_id=run_id)
        if cached is not None:
            return jsonify(cached)

    df, err = _load_simulation_df(session, run_id=run_id)
    if err:
        msg, code = err
        return jsonify({'error': msg}), code

    if visualization_type == 'process_map':
        payload = _render_process_map(df, aggregation)
    elif visualization_type == 'case_duration_dist':
        payload = _render_case_duration(df, unit)
    elif visualization_type == 'resource_heatmap':
        payload = _render_resource_heatmap(df, resource_arg)
    elif visualization_type == 'activity_duration_boxplot':
        payload = _render_activity_duration(df, activity_arg, unit)
    elif visualization_type == 'waiting_time_dist':
        payload = _render_waiting_time(df, activity_arg, resource_arg, unit)
    else:
        return jsonify({'error': 'Invalid visualization type.'}), 400

    if cache_params is not None:
        _svg_cache_set(session, visualization_type, cache_params, payload, run_id=run_id)
    return jsonify(payload)


# --- per-type renderers -------------------------------------------------------


_VALID_AGGREGATIONS = {'median', 'mean', 'min', 'max', 'sum', 'stdev'}


def _render_process_map(df, aggregation='median'):
    if aggregation not in _VALID_AGGREGATIONS:
        aggregation = 'median'
    # pm4py.discover_performance_dfg accepts a DataFrame directly; skipping
    # pm4py.convert_to_event_log saves ~1s on a 50k-event log.
    performance_dfg, start_activities, end_activities = pm4py.discover_performance_dfg(
        df,
        case_id_key='case:concept:name',
        activity_key='concept:name',
        timestamp_key='time:timestamp',
    )
    parameters = {
        dfg_perf_visualizer.Parameters.START_ACTIVITIES: start_activities,
        dfg_perf_visualizer.Parameters.END_ACTIVITIES: end_activities,
        dfg_perf_visualizer.Parameters.AGGREGATION_MEASURE: aggregation,
        "bgcolor": "white",
    }
    gviz = dfg_perf_visualizer.apply(performance_dfg, parameters=parameters)
    svg_content = gviz.pipe(format='svg', encoding='utf-8')
    logger.info("Process Map Plot Generated (aggregation=%s).", aggregation)
    return {'success': True, 'visualization': svg_content, 'aggregation': aggregation}


def _histogram(values, n_bins=30):
    """Return histogram-friendly arrays: bin centers + counts. Empty-safe."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return [], []
    if arr.size == 1 or arr.max() == arr.min():
        center = float(arr[0]) if arr.size else 0.0
        return [center], [int(arr.size)]
    counts, edges = np.histogram(arr, bins=n_bins)
    centers = ((edges[:-1] + edges[1:]) / 2.0).tolist()
    return centers, counts.astype(int).tolist()


def _summary_metrics(values, prefix='duration'):
    arr = pd.Series(values).dropna()
    if arr.empty:
        return {f'average_{prefix}': 0.0, f'median_{prefix}': 0.0,
                f'min_{prefix}': 0.0, f'max_{prefix}': 0.0}
    return {
        f'average_{prefix}': float(arr.mean()),
        f'median_{prefix}': float(arr.median()),
        f'min_{prefix}': float(arr.min()),
        f'max_{prefix}': float(arr.max()),
    }


def _render_case_duration(df, unit='min'):
    case_starts = df.groupby('case:concept:name')['start:timestamp'].min()
    case_ends = df.groupby('case:concept:name')['time:timestamp'].max()
    case_durations = _to_unit((case_ends - case_starts).dt.total_seconds(), unit)

    summary = _summary_metrics(case_durations, prefix='case_duration')
    centers, counts = _histogram(case_durations)
    logger.info("Case Duration Distribution generated (unit=%s).", unit)
    return {
        'success': True,
        'metrics': summary,
        'unit': unit,
        'histogram': {'bin_centers': centers, 'counts': counts},
    }


def _render_resource_heatmap(df, resource_name):
    if resource_name:
        df = df[df['org:resource'] == resource_name]

    df = df.assign(
        hour=df['start:timestamp'].dt.hour,
        weekday_num=df['start:timestamp'].dt.dayofweek,
    )
    utilization = (
        df.groupby(['weekday_num', 'hour']).size().unstack(fill_value=0)
        .reindex(index=np.arange(7), columns=np.arange(24), fill_value=0)
    )

    matrix = utilization.values.astype(int).tolist()
    logger.info("Resource Heatmap data generated (resource=%s).", resource_name or 'all')
    return {
        'success': True,
        'matrix': matrix,
        'weekday_labels': list(WEEKDAY_LABELS),
        'hours': list(range(24)),
        'max_value': int(utilization.values.max()) if utilization.size else 0,
        'resource': resource_name or '',
    }


def _render_activity_duration(df, activity_name, unit='min'):
    activity_df = df[df['concept:name'] == activity_name] if activity_name else df
    durations = _to_unit((activity_df['time:timestamp'] - activity_df['start:timestamp']).dt.total_seconds(), unit)

    summary = _summary_metrics(durations, prefix='duration')
    centers, counts = _histogram(durations)
    logger.info("Activity Duration data generated (activity=%s, unit=%s).", activity_name or 'all', unit)
    return {
        'success': True,
        'metrics': summary,
        'unit': unit,
        'activity': activity_name or '',
        'histogram': {'bin_centers': centers, 'counts': counts},
    }


def _render_waiting_time(df, activity_name, resource_name, unit='min'):
    activities = set(df['concept:name'].unique())
    resources = set(df['org:resource'].unique())

    if activity_name and activity_name in activities:
        df = df[df['concept:name'] == activity_name]
    if resource_name and resource_name in resources:
        df = df[df['org:resource'] == resource_name]

    waits = _to_unit((df['start:timestamp'] - df['enabled:timestamp']).dt.total_seconds(), unit)

    summary = _summary_metrics(waits, prefix='duration')
    centers, counts = _histogram(waits)
    logger.info("Waiting Time data generated (activity=%s, resource=%s, unit=%s).",
                activity_name or 'all', resource_name or 'all', unit)
    return {
        'success': True,
        'metrics': summary,
        'unit': unit,
        'activity': activity_name or '',
        'resource': resource_name or '',
        'histogram': {'bin_centers': centers, 'counts': counts},
    }
