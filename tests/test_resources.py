"""Adding and removing resources in a scenario.

The simulator looks every resource up in the weights, the calendars and the
waiting times: the four lists must always describe the same resources.
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


def _create_run(client, session_id, name, parameters, expected_status=200):
    response = client.post(f'/api/sessions/{session_id}/runs', json={'name': name, 'parameters': parameters})
    assert response.status_code == expected_status, response.data
    return response.get_json()


def _remove_like_the_ui(parameters, resource):
    """What ``removeResource`` does to the parameters held by the browser."""
    resources = parameters['resource_params']
    resources['resources'].remove(resource)
    for key in ('resource_weights', 'max_concurrency', 'calendars'):
        resources[key].pop(resource, None)
    for assigned in resources['act_to_resources'].values():
        if resource in assigned:
            assigned.remove(resource)
    parameters['waiting_time_params']['resource_waiting_times'].pop(resource, None)


def _assert_consistent(document):
    resources = document['resource_params']['resources']
    assert sorted(document['resource_params']['resource_weights']) == sorted(resources)
    assert sorted(document['resource_params']['calendars']) == sorted(resources)
    assert sorted(document['resource_params']['max_concurrency']) == sorted(resources)
    assert sorted(document['waiting_time_params']['waiting_time_distributions']) == sorted(resources)
    for assigned in document['resource_params']['act_to_resources'].values():
        assert set(assigned) <= set(resources)


def test_removed_resource_stays_removed(client, app, discovered, tiny_xes_path):
    session_id, body = discovered(tiny_xes_path)
    parameters = copy.deepcopy(body['parameters'])
    assert parameters['resource_params']['resources'] == ['r1', 'r2']

    _remove_like_the_ui(parameters, 'r2')
    run_id = _create_run(client, session_id, 'Without r2', parameters)['run']['id']

    stored = _run_document(app, run_id)
    assert stored['resource_params']['resources'] == ['r1']
    _assert_consistent(stored)
    assert 'r2' not in json.dumps(stored)

    reloaded = client.get(f'/api/runs/{run_id}').get_json()['parameters']
    assert reloaded['resource_params']['resources'] == ['r1']
    assert 'r2' not in reloaded['waiting_time_params']['resource_waiting_times']
    # C and D were only ever done by r2: they are now simulated without a resource.
    assert reloaded['resource_params']['act_to_resources'] == {'A': ['r1'], 'B': ['r1'], 'C': [], 'D': []}

    simulate = client.post(f'/api/runs/{run_id}/simulate', json={'num_instances': 5})
    assert simulate.status_code == 200, simulate.data
    assert simulate.get_json()['num_events'] == 20

    # The baseline still has both.
    baseline = client.get(f'/api/parameters/{session_id}').get_json()['parameters']
    assert baseline['resource_params']['resources'] == ['r1', 'r2']


def test_leftovers_of_a_removed_resource_are_pruned(client, app, discovered, tiny_xes_path):
    """Only the list of resources is shortened; every other map still mentions r2."""
    session_id, body = discovered(tiny_xes_path)
    parameters = copy.deepcopy(body['parameters'])
    parameters['resource_params']['resources'] = ['r1']

    stored = _run_document(app, _create_run(client, session_id, 'Without r2', parameters)['run']['id'])

    assert stored['resource_params']['resources'] == ['r1']
    _assert_consistent(stored)


@pytest.mark.parametrize("query, tree_expected", [('', False), ('?max_depth_tree=1', True)])
def test_new_resource_gets_everything_the_simulator_needs(client, app, discovered, tiny_xes_path, query, tree_expected):
    session_id, body = discovered(tiny_xes_path, query)
    parameters = copy.deepcopy(body['parameters'])
    # Only the name and the assignments: no weight, calendar or waiting time.
    parameters['resource_params']['resources'].append('new hire')
    parameters['resource_params']['act_to_resources']['A'].append('new hire')

    run_id = _create_run(client, session_id, 'One more', parameters)['run']['id']

    stored = _run_document(app, run_id)
    assert stored['resource_params']['resources'] == ['r1', 'r2', 'new hire']
    _assert_consistent(stored)
    assert stored['resource_params']['max_concurrency']['new hire'] == 1
    waiting = stored['waiting_time_params']['waiting_time_distributions']['new hire']
    # With rules every time distribution is a tree, and the default must be one too.
    assert ('0' in waiting) is tree_expected
    monday = stored['resource_params']['calendars']['new hire']['Monday']
    assert [hour for hour, working in monday.items() if working] == [str(h) for h in range(9, 17)]

    simulate = client.post(f'/api/runs/{run_id}/simulate', json={'num_instances': 30})
    assert simulate.status_code == 200, simulate.data


def test_order_of_the_resources_is_kept(client, app, discovered, tiny_xes_path):
    session_id, body = discovered(tiny_xes_path)
    parameters = copy.deepcopy(body['parameters'])
    parameters['resource_params']['resources'] = ['r2', 'r1']

    stored = _run_document(app, _create_run(client, session_id, 'Reordered', parameters)['run']['id'])

    assert stored['resource_params']['resources'] == ['r2', 'r1']


def test_partial_update_keeps_the_other_resources(client, app, discovered, tiny_xes_path):
    """A client that sends only one map does not wipe the rest."""
    session_id, body = discovered(tiny_xes_path)
    run_id = _create_run(client, session_id, 'Scenario', None)['run']['id']
    before = _run_document(app, run_id)

    update = client.put(f'/api/runs/{run_id}', json={'parameters': {
        'resource_params': {'max_concurrency': {'r1': 3}},
    }})
    assert update.status_code == 200, update.data

    after = _run_document(app, run_id)
    assert after['resource_params']['max_concurrency'] == {'r1': 3, 'r2': 1}
    assert after['resource_params']['resources'] == ['r1', 'r2']
    before['resource_params']['max_concurrency'] = {'r1': 3, 'r2': 1}
    assert after == before


def test_activities_not_mentioned_keep_their_resources(client, app, discovered, tiny_xes_path):
    session_id, body = discovered(tiny_xes_path)
    run_id = _create_run(client, session_id, 'Scenario', None)['run']['id']

    update = client.put(f'/api/runs/{run_id}', json={'parameters': {
        'resource_params': {'act_to_resources': {'A': ['r2']}},
    }})
    assert update.status_code == 200, update.data

    assert _run_document(app, run_id)['resource_params']['act_to_resources'] == {
        'A': ['r2'], 'B': ['r1'], 'C': ['r2'], 'D': ['r2'],
    }


@pytest.mark.parametrize("resource_params, message", [
    ({'resources': 'r1'}, 'resources must be a list of names'),
    ({'resources': ['r1', '']}, 'non-empty names'),
    ({'resources': ['r1', 7]}, 'non-empty names'),
    ({'max_concurrency': {'r1': 'many'}}, 'max concurrency of resource "r1"'),
    ({'act_to_resources': {'A': 'r1'}}, 'act_to_resources must map each activity to a list'),
    ({'resource_weights': {'r1': -1}}, 'weight of resource "r1" must be >= 0'),
    ({'calendars': ['Monday']}, 'calendars must map each resource'),
])
def test_invalid_resource_parameters_are_rejected(client, app, discovered, tiny_xes_path, resource_params, message):
    session_id, body = discovered(tiny_xes_path)
    run_id = _create_run(client, session_id, 'Scenario', None)['run']['id']
    before = _run_document(app, run_id)

    update = client.put(f'/api/runs/{run_id}', json={'parameters': {'resource_params': resource_params}})

    assert update.status_code == 400, update.data
    assert message in update.get_json()['error']
    assert _run_document(app, run_id) == before
