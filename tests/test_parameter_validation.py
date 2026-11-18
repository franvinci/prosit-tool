"""Weights sent by a client are checked before anything is stored.

A wrong weight is not just a wrong result: a decision tree with a loop would
make the simulator spin forever, and a missing transition would crash it.
"""

import copy
import json
import os

import pytest

from prosit_tool.extensions import db
from prosit_tool.models import SimulationRun


def _run_document(app, run_id):
    filename = db.session.get(SimulationRun, run_id).parameters_filename
    with open(os.path.join(app.config['UPLOAD_FOLDER'], filename)) as handle:
        return json.load(handle)


def _scenario(client, session_id):
    response = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Scenario'})
    assert response.status_code == 200, response.data
    return response.get_json()['run']['id']


def _put_weights(client, run_id, weights):
    return client.put(f'/api/runs/{run_id}', json={'parameters': {
        'transition_params': {'transition_weights': weights},
    }})


VALID_TREE = {
    '0': {'feature': 'A', 'threshold': 0.5, 'children': {'true': 1, 'false': 2}},
    '1': {'value': 0.25},
    '2': {'value': 0.75},
}


@pytest.mark.parametrize("weight, message", [
    (-0.1, 'must be >= 0'),
    ('0.5', 'must be a number >= 0'),
    (None, 'must be a number >= 0'),
    (True, 'must be a number >= 0'),
    ([0.5], 'must be a number >= 0'),
    (float('nan'), 'must be a number >= 0'),
    (float('inf'), 'must be a number >= 0'),
    (VALID_TREE, 'discovered without rules'),
])
def test_invalid_weight_is_rejected_and_nothing_is_stored(client, app, discovered, tiny_xes_path, weight, message):
    session_id, body = discovered(tiny_xes_path)
    run_id = _scenario(client, session_id)
    before = _run_document(app, run_id)
    name = sorted(body['parameters']['transition_params']['transition_weights'])[0]

    response = _put_weights(client, run_id, {name: weight})

    assert response.status_code == 400, response.data
    error = response.get_json()['error']
    assert message in error and name in error
    assert _run_document(app, run_id) == before


def test_unknown_transition_is_rejected(client, app, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)
    run_id = _scenario(client, session_id)

    response = _put_weights(client, run_id, {'no-such-transition': 0.5})

    assert response.status_code == 400
    assert 'Unknown transition(s) in transition_weights: no-such-transition' in response.get_json()['error']


def test_weights_must_be_an_object(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)
    response = _put_weights(client, _scenario(client, session_id), [0.5, 0.5])
    assert response.status_code == 400
    assert 'transition_weights must map each transition' in response.get_json()['error']


def test_weights_not_sent_keep_their_value(client, app, discovered, tiny_xes_path):
    """The simulator needs a weight for every transition of the net."""
    session_id, body = discovered(tiny_xes_path)
    run_id = _scenario(client, session_id)
    before = _run_document(app, run_id)['transition_params']['transition_weights']
    name = sorted(before)[0]

    assert _put_weights(client, run_id, {name: 0.3}).status_code == 200

    after = _run_document(app, run_id)['transition_params']['transition_weights']
    assert after == {**before, name: 0.3}
    assert client.post(f'/api/runs/{run_id}/simulate', json={'num_instances': 3}).status_code == 200


def test_invalid_parameters_do_not_create_a_scenario(client, app, discovered, tiny_xes_path, data_files):
    session_id, body = discovered(tiny_xes_path)
    files_before = data_files()
    parameters = copy.deepcopy(body['parameters'])
    name = sorted(parameters['transition_params']['transition_weights'])[0]
    parameters['transition_params']['transition_weights'][name] = -1

    response = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Broken', 'parameters': parameters})

    assert response.status_code == 400, response.data
    runs = client.get(f'/api/sessions/{session_id}/runs').get_json()['runs']
    assert [run['name'] for run in runs] == ['As-Is']
    assert data_files() == files_before  # no half-written snapshot left behind


def test_baseline_cannot_be_written_through_the_parameters_endpoint(client, app, discovered, tiny_xes_path):
    """The baseline is what discovery found: scenarios are edited, it is not."""
    session_id, body = discovered(tiny_xes_path)
    name = sorted(body['parameters']['transition_params']['transition_weights'])[0]
    path = os.path.join(app.config['UPLOAD_FOLDER'], body['json_filename'])
    with open(path) as handle:
        before = handle.read()

    response = client.put(f'/api/parameters/{session_id}', json={
        'transition_params': {'transition_weights': {name: 0.5}},
    })

    assert response.status_code == 405
    with open(path) as handle:
        assert handle.read() == before


# --- decision trees (models discovered with rules) ----------------------------------

@pytest.fixture
def rules_scenario(client, discovered, tiny_xes_path):
    session_id, body = discovered(tiny_xes_path, '?max_depth_tree=1')
    name = sorted(body['parameters']['transition_params']['transition_weights'])[0]
    return _scenario(client, session_id), name


def test_valid_tree_is_accepted(client, app, rules_scenario):
    run_id, name = rules_scenario

    assert _put_weights(client, run_id, {name: VALID_TREE}).status_code == 200
    assert _run_document(app, run_id)['transition_params']['transition_weights'][name] == VALID_TREE
    # Branches spelled 1/0, as prosit-pm writes them after a JSON round trip.
    one_zero = copy.deepcopy(VALID_TREE)
    one_zero['0']['children'] = {'1': 1, '0': 2}
    assert _put_weights(client, run_id, {name: one_zero}).status_code == 200
    assert client.post(f'/api/runs/{run_id}/simulate', json={'num_instances': 3}).status_code == 200


def _broken(change):
    tree = copy.deepcopy(VALID_TREE)
    change(tree)
    return tree


@pytest.mark.parametrize("tree, message", [
    (_broken(lambda t: t.pop('0')), 'has no root node "0"'),
    (_broken(lambda t: t.pop('2')), 'points to a missing node (2)'),
    (_broken(lambda t: t['0'].pop('threshold')), 'needs a numeric threshold'),
    (_broken(lambda t: t['0'].update(feature='')), 'has no feature'),
    (_broken(lambda t: t['0'].update(children={'true': 1})), 'exactly a true and a false branch'),
    (_broken(lambda t: t['0'].update(children={'true': 1, 'false': 2, 'maybe': 2})), 'exactly a true and a false branch'),
    (_broken(lambda t: t['1'].update(value=-0.5)), 'needs a weight that is a number >= 0'),
    (_broken(lambda t: t['1'].update(value='high')), 'needs a weight that is a number >= 0'),
    (_broken(lambda t: t.update({'1': {}})), 'neither a split nor a leaf'),
    (_broken(lambda t: t.update({'1': 0.5})), 'is not an object'),
    # A loop: node 1 sends the case back to the root.
    (_broken(lambda t: t.update({'1': {'feature': 'B', 'threshold': 0.5, 'children': {'true': 0, 'false': 2}}})),
     'contains a cycle'),
])
def test_malformed_tree_is_rejected(client, app, rules_scenario, tree, message):
    run_id, name = rules_scenario
    before = _run_document(app, run_id)

    response = _put_weights(client, run_id, {name: tree})

    assert response.status_code == 400, response.data
    assert message in response.get_json()['error']
    assert _run_document(app, run_id) == before


def test_parameters_must_be_an_object(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)
    run_id = _scenario(client, session_id)

    response = client.put(f'/api/runs/{run_id}', json={'parameters': ['not', 'an', 'object']})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'The parameters must be a JSON object.'
