"""Visualization endpoints: per-session activity/resource lookup and chart rendering."""

import io
import os
import logging

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import pm4py
from pm4py.visualization.dfg.variants import performance as dfg_perf_visualizer

from flask import Blueprint, request, jsonify

from app import app
from models import SimulationSession

from ._decorators import handle_api_errors

logger = logging.getLogger(__name__)
bp = Blueprint('visualization', __name__)


WEEKDAY_LABELS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

_UNIT_FACTORS = {'sec': 1, 'min': 60, 'hour': 3600, 'day': 86400}
_UNIT_LABELS = {'sec': 'seconds', 'min': 'minutes', 'hour': 'hours', 'day': 'days'}


def _to_unit(seconds_series, unit):
    """Convert a pandas series of seconds to the requested unit."""
    factor = _UNIT_FACTORS.get(unit, 60)
    return seconds_series / factor


def _unit_label(unit):
    return _UNIT_LABELS.get(unit, 'minutes')


def _figure_to_svg() -> str:
    """Render the active matplotlib figure to an SVG string and clean up."""
    buf = io.StringIO()
    try:
        plt.savefig(buf, format='svg')
        buf.seek(0)
        return buf.getvalue()
    finally:
        buf.close()
        plt.close()


def _load_simulation_df(session):
    """Load the saved simulation CSV for ``session`` and parse timestamp cols."""
    sim_log_filename = session.simulation_df_filename
    if not sim_log_filename:
        return None, ('Simulated log file not found.', 404)

    sim_log_filepath = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), sim_log_filename)
    if not os.path.exists(sim_log_filepath):
        return None, ('Simulated log file not found on server.', 404)

    df = pd.read_csv(sim_log_filepath)
    for col in ('start:timestamp', 'time:timestamp', 'enabled:timestamp'):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df, None


@bp.route('/api/get_activities_and_resources/<int:session_id>')
@handle_api_errors('Failed to get data')
def get_activities_and_resources(session_id):
    """List all activities and resources from the saved simulation log."""
    session = SimulationSession.query.get_or_404(session_id)
    df, err = _load_simulation_df(session)
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
    df, err = _load_simulation_df(session)
    if err:
        msg, code = err
        return jsonify({'error': msg}), code

    plt.style.use('seaborn-v0_8-whitegrid')

    unit = request.args.get('unit', 'min')
    if unit not in _UNIT_FACTORS:
        unit = 'min'

    if visualization_type == 'process_map':
        return _render_process_map(df, request.args.get('aggregation', 'median'))
    if visualization_type == 'case_duration_dist':
        return _render_case_duration(df, unit)
    if visualization_type == 'resource_heatmap':
        return _render_resource_heatmap(df, request.args.get('resource'))
    if visualization_type == 'activity_duration_boxplot':
        return _render_activity_duration(df, request.args.get('activity'), unit)
    if visualization_type == 'waiting_time_dist':
        return _render_waiting_time(df, request.args.get('activity'), request.args.get('resource'), unit)

    return jsonify({'error': 'Invalid visualization type.'}), 400


# --- per-type renderers -------------------------------------------------------


_VALID_AGGREGATIONS = {'median', 'mean', 'min', 'max', 'sum', 'stdev'}


def _render_process_map(df, aggregation='median'):
    if aggregation not in _VALID_AGGREGATIONS:
        aggregation = 'median'
    log = pm4py.convert_to_event_log(df)
    performance_dfg, start_activities, end_activities = pm4py.discover_performance_dfg(
        log,
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
    return jsonify({'success': True, 'visualization': svg_content, 'aggregation': aggregation})


def _render_case_duration(df, unit='min'):
    case_starts = df.groupby('case:concept:name')['start:timestamp'].min()
    case_ends = df.groupby('case:concept:name')['time:timestamp'].max()
    case_durations = _to_unit((case_ends - case_starts).dt.total_seconds(), unit)

    metrics = {
        'average_case_duration': case_durations.mean(),
        'median_case_duration': case_durations.median(),
        'min_case_duration': case_durations.min(),
        'max_case_duration': case_durations.max(),
    }

    label = _unit_label(unit)
    plt.figure(figsize=(10, 6))
    sns.histplot(case_durations, kde=True)
    plt.title('Case Duration Density Plot')
    plt.xlabel(f'Duration ({label})')
    plt.ylabel('Frequency')

    svg_content = _figure_to_svg()
    logger.info("Case Duration Distribution Plot Generated (unit=%s).", unit)
    return jsonify({'success': True, 'visualization': svg_content, 'metrics': metrics, 'unit': unit})


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

    plt.figure(figsize=(14, 6))
    sns.heatmap(utilization, cmap="YlGnBu", annot=True, fmt="d", cbar_kws={'label': 'Number of events'})

    title = f"Resource Event Count Heatmap: {resource_name}" if resource_name else "Resource Event Count Heatmap: All Resources"
    plt.title(title, fontsize=16)
    plt.xlabel("Hour of Day", fontsize=12)
    plt.ylabel("Weekday", fontsize=12)
    plt.yticks(ticks=np.arange(7) + 0.5, labels=list(WEEKDAY_LABELS), rotation=0)
    plt.tight_layout()

    svg_content = _figure_to_svg()
    logger.info("Resource Heatmap Plot Generated.")
    return jsonify({'success': True, 'visualization': svg_content})


def _render_activity_duration(df, activity_name, unit='min'):
    activity_df = df[df['concept:name'] == activity_name] if activity_name else df
    activity_df = activity_df.assign(
        duration=_to_unit((activity_df['time:timestamp'] - activity_df['start:timestamp']).dt.total_seconds(), unit)
    )

    metrics = {
        'average_duration': activity_df['duration'].mean(),
        'median_duration': activity_df['duration'].median(),
        'min_duration': activity_df['duration'].min(),
        'max_duration': activity_df['duration'].max(),
    }

    label = _unit_label(unit)
    plt.figure(figsize=(10, 6))
    sns.boxplot(y=activity_df['duration'], showfliers=False)
    plt.title(f'Activity Duration for "{activity_name}"' if activity_name else 'Activity Duration for All Activities')
    plt.ylabel(f'Duration ({label})')

    svg_content = _figure_to_svg()
    logger.info("Activity Duration Plot Generated (unit=%s).", unit)
    return jsonify({'success': True, 'visualization': svg_content, 'metrics': metrics, 'unit': unit})


def _render_waiting_time(df, activity_name, resource_name, unit='min'):
    activities = set(df['concept:name'].unique())
    resources = set(df['org:resource'].unique())

    if activity_name and activity_name in activities:
        df = df[df['concept:name'] == activity_name]
    if resource_name and resource_name in resources:
        df = df[df['org:resource'] == resource_name]

    df = df.assign(
        waiting_time=_to_unit((df['start:timestamp'] - df['enabled:timestamp']).dt.total_seconds(), unit)
    )

    metrics = {
        'average_duration': df['waiting_time'].mean(),
        'median_duration': df['waiting_time'].median(),
        'min_duration': df['waiting_time'].min(),
        'max_duration': df['waiting_time'].max(),
    }

    label = _unit_label(unit)
    plt.figure(figsize=(10, 6))
    sns.histplot(df['waiting_time'], kde=True)

    title_parts = []
    if resource_name and resource_name in resources:
        title_parts.append(f'Resource: {resource_name}')
    else:
        title_parts.append('Resource: Any')
    if activity_name and activity_name in activities:
        title_parts.append(f'Activity: {activity_name}')
    else:
        title_parts.append('Activity: Any')

    plt.title(' -- '.join(title_parts))
    plt.xlabel(f'Duration ({label})')
    plt.ylabel('Frequency')

    svg_content = _figure_to_svg()
    logger.info("Waiting Time Distribution Plot Generated (unit=%s).", unit)
    return jsonify({'success': True, 'visualization': svg_content, 'metrics': metrics, 'unit': unit})
