"""Reading a session back: process model drawing, results, discovery options."""

import pytest

from prosit_tool import prosit_integration
from prosit_tool.extensions import db
from prosit_tool.models import SimulationSession

from .conftest import event_rows, write_xes


@pytest.fixture
def drawings(monkeypatch):
    """Count how many times the Petri net is drawn (an external Graphviz run)."""
    calls = []
    original = prosit_integration.ProSiTIntegration._generate_petri_net_visualization

    def counting(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(prosit_integration.ProSiTIntegration, '_generate_petri_net_visualization', counting)
    return calls


def test_the_net_is_drawn_once_at_discovery_and_never_again(client, discovered, tiny_xes_path, drawings):
    session_id, body = discovered(tiny_xes_path)
    assert len(drawings) == 1
    drawing = body['process_model']['visualization']
    assert '<svg' in drawing

    run_id = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Scenario'}).get_json()['run']['id']
    loaded = client.get(f'/api/parameters/{session_id}').get_json()['parameters']['process_model']
    loaded_run = client.get(f'/api/runs/{run_id}').get_json()['parameters']['process_model']
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 2}).status_code == 200
    assert client.post(f'/api/runs/{run_id}/simulate', json={'num_instances': 2}).status_code == 200
    assert client.post(f'/api/metrics/{session_id}').status_code == 200

    assert len(drawings) == 1
    # What is served is the drawing made at discovery, with the ids that match it.
    for model in (loaded, loaded_run):
        assert model['visualization'] == drawing
        assert model['map_transitionName_to_id'] == body['process_model']['map_transitionName_to_id']
        assert all(node_id in drawing for node_id in model['map_transitionName_to_id'].values())


def test_session_stored_without_a_drawing_gets_one_on_demand(client, discovered, tiny_xes_path, drawings):
    session_id, _ = discovered(tiny_xes_path)
    session = db.session.get(SimulationSession, session_id)
    metadata = session.get_parameters()
    del metadata['process_model']
    session.set_parameters(metadata)
    db.session.commit()

    model = client.get(f'/api/parameters/{session_id}').get_json()['parameters']['process_model']

    assert len(drawings) == 2
    assert '<svg' in model['visualization']
    assert all(node_id in model['visualization'] for node_id in model['map_transitionName_to_id'].values())


def test_process_map_of_single_event_cases_says_there_is_nothing_to_draw(client, discovered, tmp_path):
    """No activity follows another, so there is no flow (pm4py cannot draw that)."""
    path = write_xes(event_rows(activities=('Only step',), resources=('r1',), cases=6), tmp_path / 'single.xes')
    session_id, _ = discovered(path)
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 4}).status_code == 200

    response = client.get(f'/api/get_visualization/{session_id}/process_map')

    assert response.status_code == 200, response.data
    body = response.get_json()
    assert body['success'] is True
    assert body['visualization'] == ''
    assert 'single event' in body['message']
    # The other charts of the same simulation still work.
    assert client.get(f'/api/get_visualization/{session_id}/case_duration_dist').status_code == 200


def test_process_map_of_a_normal_simulation(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)
    client.post(f'/api/simulate/{session_id}', json={'num_instances': 4})

    for aggregation in ('median', 'mean', 'not-an-aggregation'):
        body = client.get(f'/api/get_visualization/{session_id}/process_map?aggregation={aggregation}').get_json()
        assert '<svg' in body['visualization']
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
