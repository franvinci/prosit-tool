"""Parameters endpoint: GET (load) and PUT (update) parameters for a session.

Both endpoints operate on the session's baseline (As-Is) run by default. The
``/api/runs/<run_id>`` endpoints are the preferred way to address a specific
what-if scenario.
"""

import os
import json
import logging

from flask import Blueprint, request, jsonify

from app import app, db
from models import SimulationSession
from format_converters import app_entry_to_prosit, transform_distribution_tree

from ._decorators import handle_api_errors
from ._shared import load_session_prosit

logger = logging.getLogger(__name__)
bp = Blueprint('parameters', __name__)


DEFAULT_RESOURCE_WEIGHT = 0.1
DEFAULT_WORKING_HOURS = (9, 17)
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')

DEFAULT_WAITING_DIST = {
    'dist_name': 'fixed',
    'params': [1.0],
    'min_value': 1.0,
    'max_value': 1.0,
    'mean_value': 1.0,
}


def _default_calendar():
    start, end = DEFAULT_WORKING_HOURS
    return {
        day: {str(hour): (start <= hour <= end) for hour in range(24)}
        for day in WEEKDAYS
    }


@bp.route('/api/parameters/<int:session_id>')
@handle_api_errors('Failed to load parameters')
def get_parameters(session_id):
    """Return baseline parameters + a summary of all runs for a session."""
    session = SimulationSession.query.get_or_404(session_id)
    session_metadata = session.get_parameters()
    if not session_metadata:
        return jsonify({'error': 'No session metadata found'}), 404

    baseline = session.get_baseline_run()
    if baseline and baseline.parameters_filename:
        json_filename = baseline.parameters_filename
    else:
        # Legacy fallback: very old sessions kept the JSON name in
        # ``session.parameters['json_filename']`` and never got a baseline
        # run created for them.
        json_filename = session_metadata.get('json_filename')
    if not json_filename:
        return jsonify({'error': 'No parameter file found for this session'}), 404

    json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Parameter JSON file not found'}), 404

    prosit = load_session_prosit(session)
    parameters = prosit.load_parameters_from_json_file(json_filepath)
    if 'process_model' in session_metadata:
        parameters['process_model'].update(session_metadata['process_model'])
    if 'prosit_metrics' in session_metadata:
        merged = parameters.get('prosit_metrics') or {}
        merged.update(session_metadata.get('prosit_metrics') or {})
        parameters['prosit_metrics'] = merged

    runs = sorted(session.runs, key=lambda r: (not r.is_baseline, r.created_at))
    session.touch()
    db.session.commit()

    return jsonify({
        'success': True,
        'parameters': parameters,
        'status': session.status,
        'json_filename': json_filename,
        'runs': [r.to_summary() for r in runs],
        'active_run_id': baseline.id if baseline else None,
        'simulation_df_filename': baseline.simulation_df_filename if baseline else None,
        'session': {
            'id': session.id,
            'display_label': session.display_label(),
            'display_name': session.display_name,
            'filename': session.filename,
        },
    })


@bp.route('/api/parameters/<int:session_id>', methods=['PUT'])
@handle_api_errors('Failed to update parameters')
def update_parameters(session_id):
    """Backward-compat: applies UI-format edits to the baseline run.

    Prefer ``PUT /api/runs/<run_id>`` for writing to a specific scenario.
    """
    session = SimulationSession.query.get_or_404(session_id)

    new_parameters = request.get_json()
    if not new_parameters:
        return jsonify({'error': 'No parameters provided'}), 400

    baseline = session.get_baseline_run()
    if not baseline or not baseline.parameters_filename:
        return jsonify({'error': 'No baseline parameters for this session'}), 400

    json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], baseline.parameters_filename)
    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Parameter JSON file not found'}), 404

    with open(json_filepath, 'r') as f:
        prosit_json = json.load(f)

    prosit_json = convert_app_to_prosit_format(new_parameters, prosit_json)

    with open(json_filepath, 'w') as f:
        json.dump(prosit_json, f, indent=4)

    session.touch()
    db.session.commit()
    logger.info(f"Parameters updated for session {session_id} (baseline run {baseline.id})")
    return jsonify({'success': True, 'message': 'Parameters updated successfully'})


def convert_app_to_prosit_format(app_params, prosit_json):
    """Convert UI parameters back to ProSiT JSON, mutating ``prosit_json`` in place.

    Heavy distribution-conversion work is delegated to ``format_converters``.
    """
    try:
        logger.info("Converting app parameters to ProSiT format")

        if 'transition_params' in app_params and 'transition_weights' in app_params['transition_params']:
            prosit_json['transition_params']['transition_weights'] = app_params['transition_params']['transition_weights']

        if 'execution_time_params' in app_params and 'activity_durations' in app_params['execution_time_params']:
            for activity, params in app_params['execution_time_params']['activity_durations'].items():
                prosit_json['execution_time_params']['execution_time_distributions'][activity] = app_entry_to_prosit(params)

        if 'waiting_time_params' in app_params:
            wp = app_params['waiting_time_params']
            src = wp.get('resource_waiting_times') or wp.get('waiting_time') or {}
            for resource, params in src.items():
                prosit_json['waiting_time_params']['waiting_time_distributions'][resource] = app_entry_to_prosit(params)

        if 'inter_arrival_params' in app_params and 'inter_arrival_time' in app_params['inter_arrival_params']:
            inter_arrival = app_params['inter_arrival_params']['inter_arrival_time']
            distribution = inter_arrival.get('distribution') if isinstance(inter_arrival, dict) else None
            if isinstance(distribution, dict) and '0' in distribution:
                prosit_json['arrival_params']['arrival_time_distributions'] = transform_distribution_tree(distribution)
            else:
                prosit_json['arrival_params']['arrival_time_distributions'] = app_entry_to_prosit(inter_arrival)
            if isinstance(inter_arrival, dict) and 'calendar' in inter_arrival:
                prosit_json['arrival_params']['arrival_calendar'] = inter_arrival['calendar']

        if 'resource_params' in app_params:
            resource_params = app_params['resource_params']
            rp = prosit_json.setdefault('resource_params', {})

            current_resources = set(rp.get('resources', []))
            if 'resources' in resource_params:
                rp['resources'] = list(resource_params['resources'])
                current_resources.update(rp['resources'])

            if 'resource_weights' in resource_params:
                rp['resource_weights'] = resource_params['resource_weights']
                current_resources.update(resource_params['resource_weights'].keys())

            if 'max_concurrency' in resource_params:
                rp['max_concurrency'] = {
                    r: int(v) if v else 1
                    for r, v in resource_params['max_concurrency'].items()
                }

            if 'act_to_resources' in resource_params:
                rp['act_to_resources'] = resource_params['act_to_resources']

            if 'calendars' in resource_params:
                rp['calendars'] = resource_params['calendars']
                current_resources.update(resource_params['calendars'].keys())

            rp['resources'] = sorted(current_resources)

            weights = rp.setdefault('resource_weights', {})
            calendars = rp.setdefault('calendars', {})
            waiting = prosit_json.setdefault('waiting_time_params', {}).setdefault('waiting_time_distributions', {})
            for resource in current_resources:
                weights.setdefault(resource, DEFAULT_RESOURCE_WEIGHT)
                calendars.setdefault(resource, _default_calendar())
                waiting.setdefault(resource, dict(DEFAULT_WAITING_DIST))

        if 'data_attribute_params' in app_params:
            app_data_attrs = app_params['data_attribute_params']
            categorical = app_data_attrs.get('label_data_attributes_categorical') or []

            # Empirical mode encodes joint samples as stringified tuples, which
            # the UI cannot render as editable per-attribute rows. To avoid
            # silently wiping the discovery output when the user clicks Save,
            # we keep the original prosit_json data untouched in this mode.
            existing_dist = prosit_json.get('data_attribute_params', {}).get('distribution_data_attributes', {})
            existing_mode = existing_dist.get('mode') if isinstance(existing_dist, dict) else None
            if existing_mode == 'empirical' or app_data_attrs.get('distribution_mode') == 'empirical':
                prosit_json.setdefault('data_attribute_params', {}).update({
                    'label_data_attributes': app_data_attrs.get('label_data_attributes'),
                    'label_data_attributes_categorical': app_data_attrs.get('label_data_attributes_categorical'),
                    'attribute_values_label_categorical': app_data_attrs.get('attribute_values_label_categorical'),
                })
                # ``distribution_data_attributes`` stays as discovered.
                return prosit_json

            prosit_data = {}
            for attr, params in (app_data_attrs.get('distribution_data_attributes') or {}).items():
                if attr in categorical:
                    if isinstance(params, dict) and 'values' in params:
                        values = params.get('values') or {}
                    elif isinstance(params, dict):
                        values = params
                    else:
                        values = {}
                    prosit_data[attr] = {'type': 'categorical', 'values': values}
                    continue
                entry = app_entry_to_prosit(params)
                prosit_data[attr] = {
                    'type': 'continuous',
                    'dist': entry.get('dist_name'),
                    'params': entry.get('params'),
                    'min': entry.get('min_value'),
                    'max': entry.get('max_value'),
                    'mean': entry.get('mean_value'),
                }
            existing = prosit_json.get('data_attribute_params', {}).get('distribution_data_attributes', {})
            existing_mode = existing.get('mode') if isinstance(existing, dict) else None
            prosit_json.setdefault('data_attribute_params', {})['distribution_data_attributes'] = {
                'mode': existing_mode or 'distribution',
                'data': prosit_data,
            }
            prosit_json['data_attribute_params'].update({
                'label_data_attributes': app_data_attrs.get('label_data_attributes'),
                'label_data_attributes_categorical': app_data_attrs.get('label_data_attributes_categorical'),
                'attribute_values_label_categorical': app_data_attrs.get('attribute_values_label_categorical'),
            })

        return prosit_json

    except Exception as e:
        logger.error(f"Error converting app to ProSiT format: {e}")
        raise
