"""Reading a session back: process model drawing, results, discovery options."""

import pytest

from prosit_tool.extensions import db
from prosit_tool.models import SimulationSession

from .conftest import event_rows, write_xes


def _old_style_model():
    """What versions before 1.1 stored with a session: a drawing made by Graphviz."""
    return {
        'visualization': '<svg><g id="node1"><title>140213</title></g></svg>',
        'map_transitionName_to_id': {'A': '140213'},
        'activities': ['A'],
        'transitions': ['stale'],
        'places': ['stale'],
        'fitness': 0.42,
        'precision': 0.5,
        'f_measure': 0.4565,
    }


def test_the_model_is_described_for_the_page_to_draw(client, discovered, tiny_xes_path):
    session_id, body = discovered(tiny_xes_path)

    model = body['parameters']['process_model']

    assert model['dot'].startswith('digraph')
    assert 'visualization' not in model and 'map_transitionName_to_id' not in model
    transitions = {node_id: node for node_id, node in model['nodes'].items() if node['type'] == 'transition'}
    assert sorted(node['label'] for node in transitions.values() if not node['silent']) == ['A', 'B', 'C', 'D']
    assert sorted(node['name'] for node in transitions.values()) == sorted(model['transitions'])
    assert all(f'{node_id} [' in model['dot'] for node_id in model['nodes'])
    # the answer of the discovery carries the same description at its top level
    assert body['process_model'] == model


def test_the_description_is_the_same_every_time_the_session_is_opened(client, discovered, tiny_xes_path):
    """Same text, same layout: the net does not move around between one visit and the next."""
    session_id, body = discovered(tiny_xes_path)
    discovered_model = body['parameters']['process_model']
    run_id = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Scenario'}).get_json()['run']['id']

    reloaded = client.get(f'/api/parameters/{session_id}').get_json()['parameters']['process_model']
    of_scenario = client.get(f'/api/runs/{run_id}').get_json()['parameters']['process_model']

    for model in (reloaded, of_scenario):
        assert model['dot'] == discovered_model['dot']
        assert model['nodes'] == discovered_model['nodes']
        # fitness and precision need the event log: they are kept from the discovery
        assert model['fitness'] == discovered_model['fitness'] > 0
        assert model['precision'] == discovered_model['precision'] > 0


def test_only_the_metrics_of_the_model_are_stored_with_the_session(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)

    stored = db.session.get(SimulationSession, session_id).get_parameters()['process_model']

    assert sorted(stored) == ['f_measure', 'fitness', 'precision']


def test_session_stored_by_an_older_version_is_described_from_its_net(client, discovered, tiny_xes_path):
    """No migration: the old drawing is ignored, the metrics it came with are kept."""
    session_id, body = discovered(tiny_xes_path)
    session = db.session.get(SimulationSession, session_id)
    metadata = session.get_parameters()
    metadata['process_model'] = _old_style_model()
    session.set_parameters(metadata)
    db.session.commit()

    model = client.get(f'/api/parameters/{session_id}').get_json()['parameters']['process_model']

    assert model['dot'] == body['parameters']['process_model']['dot']
    assert 'visualization' not in model and 'map_transitionName_to_id' not in model
    assert sorted(model['activities']) == ['A', 'B', 'C', 'D']
    assert (model['fitness'], model['precision'], model['f_measure']) == (0.42, 0.5, 0.4565)


def test_no_graphviz_program_is_ever_run(client, discovered, tiny_xes_path, monkeypatch):
    """The page draws; the server only describes. Nothing may call the `dot` program."""
    import graphviz.backend.execute as execute

    def called(*args, **kwargs):
        raise AssertionError(f'a Graphviz program was run: {args}')

    for name in ('run_check', 'run'):
        if hasattr(execute, name):
            monkeypatch.setattr(execute, name, called)
    import subprocess
    real_run = subprocess.run

    def guarded(command, *args, **kwargs):
        program = command[0] if isinstance(command, (list, tuple)) else str(command)
        assert 'dot' not in str(program).split('/')[-1], f'a Graphviz program was run: {command}'
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', guarded)

    session_id, body = discovered(tiny_xes_path)
    assert client.get(f'/api/parameters/{session_id}').status_code == 200
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 3}).status_code == 200
    process_map = client.get(f'/api/get_visualization/{session_id}/process_map')
    assert process_map.status_code == 200 and process_map.get_json()['dot'].startswith('digraph')


def test_process_map_of_single_event_cases_says_there_is_nothing_to_draw(client, discovered, tmp_path):
    """No activity follows another, so there is no flow (pm4py cannot draw that)."""
    path = write_xes(event_rows(activities=('Only step',), resources=('r1',), cases=6), tmp_path / 'single.xes')
    session_id, _ = discovered(path)
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 4}).status_code == 200

    response = client.get(f'/api/get_visualization/{session_id}/process_map')

    assert response.status_code == 200, response.data
    body = response.get_json()
    assert body['success'] is True
    assert body['dot'] == ''
    assert 'single event' in body['message']
    # The other charts of the same simulation still work.
    assert client.get(f'/api/get_visualization/{session_id}/case_duration_dist').status_code == 200


def test_process_map_of_a_normal_simulation(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)
    client.post(f'/api/simulate/{session_id}', json={'num_instances': 4})

    for aggregation in ('median', 'mean', 'not-an-aggregation'):
        body = client.get(f'/api/get_visualization/{session_id}/process_map?aggregation={aggregation}').get_json()
        # described by pm4py, drawn by the page
        assert body['dot'].startswith('digraph') and 'visualization' not in body
        assert all(f'label={activity}' in body['dot'] or f'label="{activity}' in body['dot'] for activity in 'ABCD')
        assert 'fontname="Helvetica"' in body['dot']
        assert body['aggregation'] == ('median' if aggregation == 'not-an-aggregation' else aggregation)
        assert 'message' not in body


@pytest.mark.parametrize("query, message", [
    ('?max_depth_tree=9', 'max_depth_tree must be between 0 and 5'),
    ('?max_depth_tree=-1', 'max_depth_tree must be between 0 and 5'),
    ('?max_depth_tree=deep', "max_depth_tree: expected an integer, got 'deep'"),
    ('?grace_period=0', 'grace_period must be at least 1'),
    ('?multitasking_thr=1.5', 'multitasking_thr must be between 0 and 1'),
    ('?random_state=seed', "random_state: expected an integer, got 'seed'"),
    ('?attribute_mode=exact', "attribute_mode must be one of ('distribution', 'empirical')"),
])
def test_invalid_discovery_option_is_refused_before_anything_runs(client, upload, tiny_xes_path, data_files, query, message):
    uploaded = upload(tiny_xes_path).get_json()

    response = client.post(f"/api/discover/{uploaded['session_id']}{query}")

    assert response.status_code == 400, response.data
    assert response.get_json()['error'] == message
    assert data_files() == ([uploaded['filename']], [])
    db.session.expire_all()
    assert db.session.get(SimulationSession, uploaded['session_id']).status == 'uploaded'


def test_scenario_names_clash_with_the_baseline_whatever_the_case(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)

    for name in ('As-Is', 'as-is', ' AS-IS '):
        response = client.post(f'/api/sessions/{session_id}/runs', json={'name': name})
        assert response.status_code == 400, name
        assert 'reserved' in response.get_json()['error']

    run_id = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Scenario'}).get_json()['run']['id']
    rename = client.patch(f'/api/runs/{run_id}', json={'name': 'as-is'})
    assert rename.status_code == 400 and 'reserved' in rename.get_json()['error']


def test_scenario_from_a_run_that_is_not_a_number(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)

    response = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Scenario', 'from_run_id': 'first'})

    assert response.status_code == 400
    assert response.get_json()['error'] == "from_run_id must be an integer, got 'first'"
    assert client.post(f'/api/sessions/{session_id}/runs',
                       json={'name': 'Scenario', 'from_run_id': 9999}).status_code == 404
