"""Parameters of a session: loading them for the UI, and storing what it sends back.

``GET /api/parameters/<session_id>`` returns the baseline (As-Is) scenario,
which is what discovery found and is never written again. Scenarios are read
and written through ``/api/runs/<run_id>``.

This module also owns the translation of what the UI sends back into the
prosit-pm JSON document of a run (``convert_app_to_prosit_format``).
"""

import os
import json
import logging
import math

from flask import Blueprint, current_app, jsonify

from ..extensions import db
from ..models import SimulationSession
from ..format_converters import (
    app_entry_to_prosit,
    attribute_entry_from_prosit,
    merge_app_entry,
    prosit_entry_to_app,
    transform_distribution_tree,
)

from ._decorators import handle_api_errors
from ._shared import load_session_prosit, write_json_atomic

logger = logging.getLogger(__name__)
bp = Blueprint('parameters', __name__)


DEFAULT_RESOURCE_WEIGHT = 0.1
DEFAULT_WORKING_HOURS = (9, 17)  # from 9:00 up to, not including, 17:00
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')

DEFAULT_WAITING_DIST = {
    'dist_name': 'fixed',
    'params': [1.0],
    'min_value': 1.0,
    'max_value': 1.0,
    'mean_value': 1.0,
}

# Branch keys of a split node. prosit-pm writes them as true/false when a tree
# is fresh in memory and as 1/0 after a JSON round trip; both mean the same.
_TRUE_KEYS = ('true', '1', 'True')
_FALSE_KEYS = ('false', '0', 'False')


class ParameterError(ValueError):
    """The parameters sent by the client cannot be applied.

    The message is meant for the user and is returned as a 400 response.
    """


def _default_calendar():
    start, end = DEFAULT_WORKING_HOURS
    return {
        day: {str(hour): (start <= hour < end) for hour in range(24)}
        for day in WEEKDAYS
    }


def _default_waiting(rules_mode):
    """Waiting time of a resource the log knows nothing about.

    With rules every time distribution is a decision tree, so the default has
    to be a tree too (a single leaf): prosit-pm cannot load a plain
    distribution there.
    """
    if not rules_mode:
        return dict(DEFAULT_WAITING_DIST)
    value = DEFAULT_WAITING_DIST['mean_value']
    return {'0': {
        'value': value,
        'dist': {
            'dist_name': DEFAULT_WAITING_DIST['dist_name'],
            'params': list(DEFAULT_WAITING_DIST['params']),
            'min_value': DEFAULT_WAITING_DIST['min_value'],
            'max_value': DEFAULT_WAITING_DIST['max_value'],
        },
    }}


def is_rules_mode(prosit_json):
    """Whether the document was discovered with decision rules.

    Same inference prosit-pm makes for documents written before it stored the
    flag: in rules mode the arrival model is a tree, which has no ``mean_value``.
    """
    if 'rules_mode' in prosit_json:
        return bool(prosit_json['rules_mode'])
    arrival = prosit_json.get('arrival_params', {}).get('arrival_time_distributions', {})
    return isinstance(arrival, dict) and 'mean_value' not in arrival


@bp.route('/api/parameters/<int:session_id>')
@handle_api_errors('Failed to load parameters')
def get_parameters(session_id):
    """Return baseline parameters + a summary of all runs for a session."""
    session = db.get_or_404(SimulationSession, session_id)
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

    json_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], json_filename)
    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Parameter JSON file not found'}), 404

    parameters = load_parameters_for_ui(session, json_filepath)

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


def load_parameters_for_ui(session, json_filepath):
    """Parameters of one run in UI format, with the session's process model.

    The drawing of the Petri net and the accuracy metrics are computed once,
    at discovery, and stored with the session: they are read back from there
    instead of being recomputed on every request.
    """
    session_metadata = session.get_parameters() or {}
    prosit = load_session_prosit(session)
    parameters = prosit.load_parameters_from_json_file(json_filepath)

    stored_model = session_metadata.get('process_model')
    if stored_model:
        parameters['process_model'].update(stored_model)
    if not parameters['process_model'].get('visualization'):
        # Session stored without a drawing: make one for this response.
        parameters['process_model'].update(prosit.render_process_model())

    if 'prosit_metrics' in session_metadata:
        merged = parameters.get('prosit_metrics') or {}
        merged.update(session_metadata.get('prosit_metrics') or {})
        parameters['prosit_metrics'] = merged
    return parameters


def apply_ui_parameters_to_file(json_filepath, ui_params):
    """Apply UI-format parameters to the prosit-pm JSON document at ``json_filepath``.

    The file is rewritten only if every parameter is valid; on ``ParameterError``
    it is left exactly as it was.
    """
    with open(json_filepath, 'r') as f:
        prosit_json = json.load(f)
    prosit_json = convert_app_to_prosit_format(ui_params, prosit_json)
    write_json_atomic(json_filepath, prosit_json)


# --- UI format -> prosit-pm JSON ------------------------------------------------


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_weight_tree(tree, where):
    """Check that ``tree`` is a well-formed decision tree with weight leaves.

    A malformed tree is not only a wrong result: the simulator walks it with a
    ``while`` loop, so a cycle would hang the simulation for good.
    """
    if '0' not in tree:
        raise ParameterError(f'The decision tree of {where} has no root node "0".')
    for node_id, node in tree.items():
        if not isinstance(node, dict):
            raise ParameterError(f'Node {node_id} of the decision tree of {where} is not an object.')
        if 'feature' in node or 'children' in node:
            if not isinstance(node.get('feature'), str) or not node['feature']:
                raise ParameterError(f'Node {node_id} of the decision tree of {where} has no feature.')
            if not _finite_number(node.get('threshold')):
                raise ParameterError(f'Node {node_id} of the decision tree of {where} needs a numeric threshold.')
            children = node.get('children')
            if not isinstance(children, dict):
                raise ParameterError(f'Node {node_id} of the decision tree of {where} has no branches.')
            on_true = [children[k] for k in _TRUE_KEYS if k in children]
            on_false = [children[k] for k in _FALSE_KEYS if k in children]
            if len(on_true) != 1 or len(on_false) != 1 or len(children) != 2:
                raise ParameterError(
                    f'Node {node_id} of the decision tree of {where} needs exactly a true and a false branch.'
                )
            for child in (on_true[0], on_false[0]):
                if str(child) not in tree:
                    raise ParameterError(
                        f'Node {node_id} of the decision tree of {where} points to a missing node ({child}).'
                    )
        elif 'value' in node:
            if not _finite_number(node['value']) or node['value'] < 0:
                raise ParameterError(
                    f'Leaf {node_id} of the decision tree of {where} needs a weight that is a number >= 0.'
                )
        else:
            raise ParameterError(f'Node {node_id} of the decision tree of {where} is neither a split nor a leaf.')

    # Every path from the root must end in a leaf without visiting a node twice.
    on_path = set()

    def walk(node_id):
        if node_id in on_path:
            raise ParameterError(f'The decision tree of {where} contains a cycle at node {node_id}.')
        children = tree[node_id].get('children')
        if not children:
            return
        on_path.add(node_id)
        for child in children.values():
            walk(str(child))
        on_path.discard(node_id)

    walk('0')


def _validate_weight(value, where, rules_mode):
    """A weight is a number >= 0 or, in a model discovered with rules, a tree."""
    if _finite_number(value):
        if value < 0:
            raise ParameterError(f'The weight of {where} must be >= 0, got {value}.')
        return value
    if isinstance(value, dict):
        if not rules_mode:
            raise ParameterError(
                f'The weight of {where} is a decision tree, but this model was discovered '
                f'without rules: its weights are plain numbers.'
            )
        _validate_weight_tree(value, where)
        return value
    raise ParameterError(f'The weight of {where} must be a number >= 0, got {value!r}.')


def _validate_weights(weights, kind, rules_mode, known=None):
    if not isinstance(weights, dict):
        raise ParameterError(f'{kind}_weights must map each {kind} to its weight.')
    if known:
        unknown = sorted(str(name) for name in weights if name not in known)
        if unknown:
            shown = ', '.join(unknown[:5]) + (', …' if len(unknown) > 5 else '')
            raise ParameterError(f'Unknown {kind}(s) in {kind}_weights: {shown}.')
    return {name: _validate_weight(weight, f'{kind} "{name}"', rules_mode) for name, weight in weights.items()}


def _unique_names(names, what):
    if not isinstance(names, (list, tuple)):
        raise ParameterError(f'{what} must be a list of names.')
    unique = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ParameterError(f'{what} must contain non-empty names, got {name!r}.')
        if name not in unique:
            unique.append(name)
    return unique


def _apply_resources(resource_params, prosit_json, rules_mode):
    """Apply the resource section, keeping every per-resource map consistent.

    The simulator looks every resource up in the weights, the calendars and the
    waiting times, so the four of them must always list the same resources. When
    the UI sends its list of resources that list is the truth: a resource that
    is not in it is removed everywhere, and a new one gets defaults everywhere.
    """
    if not isinstance(resource_params, dict):
        raise ParameterError('resource_params must be an object.')

    rp = prosit_json.setdefault('resource_params', {})
    waiting = prosit_json.setdefault('waiting_time_params', {}).setdefault('waiting_time_distributions', {})

    if 'resources' in resource_params:
        resources = _unique_names(resource_params['resources'], 'resources')
    else:
        # Partial update: keep the stored list, plus any resource that is
        # introduced by giving it a weight or a calendar.
        resources = list(rp.get('resources', []))
        for key in ('resource_weights', 'calendars'):
            for name in (resource_params.get(key) or {}):
                if name not in resources:
                    resources.append(name)

    weights = dict(rp.get('resource_weights') or {})
    if 'resource_weights' in resource_params:
        weights = _validate_weights(resource_params['resource_weights'], 'resource', rules_mode)

    calendars = dict(rp.get('calendars') or {})
    if 'calendars' in resource_params:
        if not isinstance(resource_params['calendars'], dict):
            raise ParameterError('calendars must map each resource to its weekly calendar.')
        calendars = dict(resource_params['calendars'])

    if 'max_concurrency' in rp:
        max_concurrency = dict(rp['max_concurrency'] or {})
    else:
        # Documents written before prosit-pm 1.0 only list the resources that
        # multitask; read them the way prosit-pm does.
        max_concurrency = {name: 100 for name in rp.get('multitasking_resource', [])}
    if 'max_concurrency' in resource_params:
        if not isinstance(resource_params['max_concurrency'], dict):
            raise ParameterError('max_concurrency must map each resource to a number of parallel tasks.')
        max_concurrency = {}
        for name, value in resource_params['max_concurrency'].items():
            try:
                max_concurrency[name] = max(1, int(value)) if value else 1
            except (TypeError, ValueError):
                raise ParameterError(
                    f'The max concurrency of resource "{name}" must be a whole number >= 1, got {value!r}.'
                ) from None

    act_to_resources = dict(rp.get('act_to_resources') or {})
    if 'act_to_resources' in resource_params:
        provided = resource_params['act_to_resources']
        if not isinstance(provided, dict) or not all(isinstance(v, (list, tuple)) for v in provided.values()):
            raise ParameterError('act_to_resources must map each activity to a list of resources.')
        # Activities the client does not mention keep their resources: the
        # simulator needs an entry for every activity of the model.
        act_to_resources.update(provided)

    kept = set(resources)
    rp['resources'] = resources
    rp['resource_weights'] = {r: weights.get(r, DEFAULT_RESOURCE_WEIGHT) for r in resources}
    rp['calendars'] = {r: calendars.get(r) or _default_calendar() for r in resources}
    rp['max_concurrency'] = {r: max_concurrency.get(r, 1) for r in resources}
    rp['act_to_resources'] = {
        activity: [r for r in assigned if r in kept]
        for activity, assigned in act_to_resources.items()
    }
    for name in list(waiting):
        if name not in kept:
            del waiting[name]
    for name in resources:
        if name not in waiting:
            waiting[name] = _default_waiting(rules_mode)


def _apply_data_attributes(app_data_attrs, prosit_json):
    if not isinstance(app_data_attrs, dict):
        raise ParameterError('data_attribute_params must be an object.')
    section = prosit_json.setdefault('data_attribute_params', {})

    # Only what the client actually sent: a missing key must not blank the
    # lists prosit-pm reads when it loads the document.
    for key in ('label_data_attributes', 'label_data_attributes_categorical', 'attribute_values_label_categorical'):
        if app_data_attrs.get(key) is not None:
            section[key] = app_data_attrs[key]

    existing = section.get('distribution_data_attributes')
    existing_mode = existing.get('mode') if isinstance(existing, dict) else None
    if existing_mode == 'empirical' or app_data_attrs.get('distribution_mode') == 'empirical':
        # Empirical mode encodes joint samples as stringified tuples, which the
        # UI cannot render as editable per-attribute rows: the discovered data
        # stays as it is.
        return
    if 'distribution_data_attributes' not in app_data_attrs:
        return

    stored_data = existing.get('data') if isinstance(existing, dict) and 'data' in existing else (existing or {})
    categorical = section.get('label_data_attributes_categorical') or []
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

        stored = stored_data.get(attr) if isinstance(stored_data, dict) else None
        stored_entry = attribute_entry_from_prosit(stored)
        if stored_entry is not None and params == prosit_entry_to_app(stored_entry):
            prosit_data[attr] = stored  # not edited: keep it to the last bit
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
    if not prosit_data and existing is None:
        # A log without data attributes: prosit-pm stores "no attributes" as
        # null, and that is what it must find again.
        return
    section['distribution_data_attributes'] = {
        'mode': existing_mode or 'distribution',
        'data': prosit_data,
    }


def convert_app_to_prosit_format(app_params, prosit_json):
    """Convert UI parameters back to ProSiT JSON, mutating ``prosit_json`` in place.

    Raises ``ParameterError`` when a value cannot be applied. Callers that write
    the result to disk must do so only after this returns.
    """
    if not isinstance(app_params, dict):
        raise ParameterError('The parameters must be a JSON object.')
    rules_mode = is_rules_mode(prosit_json)

    transition_params = app_params.get('transition_params')
    if isinstance(transition_params, dict) and 'transition_weights' in transition_params:
        stored = prosit_json.setdefault('transition_params', {}).setdefault('transition_weights', {})
        # Merged, not replaced: the simulator needs a weight for every
        # transition of the net, whether or not the client sent all of them.
        stored.update(_validate_weights(
            transition_params['transition_weights'], 'transition', rules_mode, known=stored,
        ))

    execution_params = app_params.get('execution_time_params')
    if isinstance(execution_params, dict) and 'activity_durations' in execution_params:
        stored = prosit_json.setdefault('execution_time_params', {}).setdefault('execution_time_distributions', {})
        for activity, entry in (execution_params['activity_durations'] or {}).items():
            stored[activity] = merge_app_entry(stored.get(activity), entry)

    waiting_params = app_params.get('waiting_time_params')
    if isinstance(waiting_params, dict):
        stored = prosit_json.setdefault('waiting_time_params', {}).setdefault('waiting_time_distributions', {})
        source = waiting_params.get('resource_waiting_times') or waiting_params.get('waiting_time') or {}
        for resource, entry in source.items():
            stored[resource] = merge_app_entry(stored.get(resource), entry)

    inter_arrival_params = app_params.get('inter_arrival_params')
    if isinstance(inter_arrival_params, dict) and 'inter_arrival_time' in inter_arrival_params:
        inter_arrival = inter_arrival_params['inter_arrival_time']
        arrival = prosit_json.setdefault('arrival_params', {})
        if isinstance(inter_arrival, dict):
            distribution = inter_arrival.get('distribution')
            if isinstance(distribution, dict) and '0' in distribution:
                arrival['arrival_time_distributions'] = transform_distribution_tree(distribution)
            elif 'distribution' in inter_arrival:
                entry = {key: inter_arrival[key] for key in ('distribution', 'parameters') if key in inter_arrival}
                arrival['arrival_time_distributions'] = merge_app_entry(
                    arrival.get('arrival_time_distributions'), entry,
                )
            if 'calendar' in inter_arrival:
                arrival['arrival_calendar'] = inter_arrival['calendar']

    if 'resource_params' in app_params:
        _apply_resources(app_params['resource_params'], prosit_json, rules_mode)

    if 'data_attribute_params' in app_params:
        _apply_data_attributes(app_params['data_attribute_params'], prosit_json)

    return prosit_json
