"""A what-if scenario saved without changes is the scenario it was copied from.

The browser sends the whole parameter set back on every save. Whatever the user
did not edit has to come out of that round trip exactly as it went in, or the
comparison between As-Is and a what-if measures the conversion instead of the
change the user made.
"""

import copy
import io
import json
import os

import pandas as pd
import pytest

from prosit_tool.extensions import db
from prosit_tool.models import SimulationRun

DISTRIBUTION_SECTIONS = (
    ('execution_time_params', 'execution_time_distributions'),
    ('waiting_time_params', 'waiting_time_distributions'),
)


def _document(app, filename):
    with open(os.path.join(app.config['UPLOAD_FOLDER'], filename)) as handle:
        return json.load(handle)


def _run_document(app, run_id):
    return _document(app, db.session.get(SimulationRun, run_id).parameters_filename)


def _create_run(client, session_id, name, parameters):
    response = client.post(f'/api/sessions/{session_id}/runs', json={'name': name, 'parameters': parameters})
    assert response.status_code == 200, response.data
    return response.get_json()['run']['id']


def _canonical(node):
    """A document with the branch keys of decision trees spelled one way.

    prosit-pm writes them as true/false or as 1/0 depending on whether the tree
    went through a JSON round trip; it reads both as the same thing.
    """
    spelling = {'true': 'true', 'True': 'true', '1': 'true', 'false': 'false', 'False': 'false', '0': 'false'}
    if isinstance(node, dict):
        if set(node) == {'feature', 'threshold', 'children'}:
            return {
                'feature': node['feature'],
                'threshold': node['threshold'],
                'children': {spelling[str(k)]: int(v) for k, v in node['children'].items()},
            }
        return {key: _canonical(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_canonical(value) for value in node]
    return node


def test_scenario_saved_without_edits_is_identical_to_the_baseline(client, app, discovered, small_xes_path):
    session_id, body = discovered(small_xes_path)
    baseline = _document(app, body['json_filename'])

    # The log has to contain the families the old conversion altered, or this
    # test proves nothing.
    families = {
        entry['dist_name']
        for section, key in DISTRIBUTION_SECTIONS
        for entry in baseline[section][key].values()
    }
    shifted_exponentials = [
        entry for section, key in DISTRIBUTION_SECTIONS for entry in baseline[section][key].values()
        if entry['dist_name'] == 'expon' and entry['params'][0] != 0
    ]
    assert 'uniform' in families or shifted_exponentials, families

    run_id = _create_run(client, session_id, 'Copy of As-Is', body['parameters'])

    assert _run_document(app, run_id) == baseline

    # Saving it again, as "Save Changes" does, still changes nothing.
    reloaded = client.get(f'/api/runs/{run_id}').get_json()['parameters']
    assert client.put(f'/api/runs/{run_id}', json={'parameters': reloaded}).status_code == 200
    assert _run_document(app, run_id) == baseline


def test_scenario_saved_without_edits_is_identical_with_decision_rules(client, app, discovered, tiny_xes_path):
    session_id, body = discovered(tiny_xes_path, '?max_depth_tree=1')
    baseline = _document(app, body['json_filename'])
    assert baseline['rules_mode'] is True
    assert any('0' in entry for entry in baseline['execution_time_params']['execution_time_distributions'].values())

    run_id = _create_run(client, session_id, 'Copy of As-Is', body['parameters'])
    assert _canonical(_run_document(app, run_id)) == _canonical(baseline)

    # Same after the scenario is loaded from disk and saved again.
    reloaded = client.get(f'/api/runs/{run_id}').get_json()['parameters']
    assert client.put(f'/api/runs/{run_id}', json={'parameters': reloaded}).status_code == 200
    assert _canonical(_run_document(app, run_id)) == _canonical(baseline)


def test_editing_one_distribution_changes_only_that_one(client, app, discovered, small_xes_path):
    session_id, body = discovered(small_xes_path)
    baseline = _document(app, body['json_filename'])
    parameters = copy.deepcopy(body['parameters'])

    durations = parameters['execution_time_params']['activity_durations']
    activity = next(name for name, entry in durations.items() if entry['distribution'] == 'norm')
    durations[activity]['parameters']['mean'] = 123.0

    stored = _run_document(app, _create_run(client, session_id, 'One edit', parameters))

    edited = stored['execution_time_params']['execution_time_distributions']
    original = baseline['execution_time_params']['execution_time_distributions']
    assert edited[activity]['params'][0] == 123.0
    assert edited[activity]['params'][1] == original[activity]['params'][1]
    assert {k: v for k, v in edited.items() if k != activity} == {k: v for k, v in original.items() if k != activity}
    for section in ('waiting_time_params', 'arrival_params', 'resource_params', 'transition_params',
                    'data_attribute_params'):
        assert stored[section] == baseline[section], section


def test_family_picked_in_the_ui_is_not_clipped_to_made_up_bounds(client, app, discovered, tiny_xes_path):
    """The editor sends no min/max right after another family is selected."""
    session_id, body = discovered(tiny_xes_path)
    parameters = copy.deepcopy(body['parameters'])
    parameters['execution_time_params']['activity_durations']['A'] = {
        'distribution': 'norm', 'parameters': {'mean': 120, 'std': 30},
    }

    stored = _run_document(app, _create_run(client, session_id, 'Normal A', parameters))

    entry = stored['execution_time_params']['execution_time_distributions']['A']
    assert entry['params'] == [120.0, 30.0]
    assert entry['min_value'] < 120 - 2 * 30
    assert entry['max_value'] > 120 + 2 * 30


def test_editing_a_fixed_leaf_changes_the_simulated_durations(client, app, discovered, tiny_xes_path):
    """Rules mode: the duration of an activity is a tree; here a single fixed leaf."""
    session_id, body = discovered(tiny_xes_path, '?max_depth_tree=1')
    parameters = copy.deepcopy(body['parameters'])
    tree = parameters['execution_time_params']['activity_durations']['B']
    assert list(tree) == ['0'] and tree['0']['dist']['dist_name'] == 'fixed', tree
    assert tree['0']['value'] == 10.0

    # What the tree editor produces when the user types 25 in "Fixed Value".
    tree['0']['dist']['params'] = {'value': 25.0}
    run_id = _create_run(client, session_id, 'B takes 25 minutes', parameters)

    leaf = client.get(f'/api/runs/{run_id}').get_json()['parameters']['execution_time_params']['activity_durations']['B']['0']
    assert leaf['value'] == 25.0
    assert leaf['dist']['params'] == [25.0]

    def durations_of_b(simulate_url):
        response = client.post(simulate_url, json={'num_instances': 20, 'start_timestamp': '2024-01-01T08:00'})
        assert response.status_code == 200, response.data
        csv = client.get(f"/api/download/{response.get_json()['sim_output_filename']}")
        df = pd.read_csv(io.BytesIO(csv.data), parse_dates=['start:timestamp', 'time:timestamp'])
        b = df[df['concept:name'] == 'B']
        return (b['time:timestamp'] - b['start:timestamp']).dt.total_seconds() / 60

    # Durations are counted in working time, so an event that runs into a
    # closed hour of the resource's calendar lasts longer on the clock.
    assert durations_of_b(f'/api/simulate/{session_id}').min() == pytest.approx(10.0)
    edited = durations_of_b(f'/api/runs/{run_id}/simulate')
    assert edited.min() == pytest.approx(25.0)
    assert (edited >= 25.0 - 1e-9).all()
