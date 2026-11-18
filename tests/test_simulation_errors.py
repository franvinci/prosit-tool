"""Simulation requests that cannot be served say why, and leave the session alone."""

import io

import pandas as pd
import pytest

from prosit_tool import prosit_integration
from prosit_tool.extensions import db
from prosit_tool.models import SimulationSession


def _status(session_id):
    db.session.expire_all()
    return db.session.get(SimulationSession, session_id).status


def test_unknown_session_and_run_are_not_found(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)

    assert client.post('/api/simulate/9999', json={'num_instances': 2}).status_code == 404
    assert client.post('/api/runs/9999/simulate', json={'num_instances': 2}).status_code == 404

    response = client.post(f'/api/simulate/{session_id}', json={'num_instances': 2, 'run_id': 9999})
    assert response.status_code == 404
    assert response.get_json()['error'] == 'Run not found in this session'
    assert _status(session_id) == 'ready'


def test_run_of_another_session_is_not_found(client, discovered, tiny_xes_path):
    first, _ = discovered(tiny_xes_path)
    second, _ = discovered(tiny_xes_path)
    run_of_first = client.get(f'/api/sessions/{first}/runs').get_json()['runs'][0]['id']

    response = client.post(f'/api/simulate/{second}', json={'num_instances': 2, 'run_id': run_of_first})

    assert response.status_code == 404


@pytest.mark.parametrize("body, message", [
    ({'num_instances': 2, 'start_timestamp': 'next monday'}, 'start_timestamp must be an ISO 8601 date and time'),
    ({'num_instances': 2, 'start_timestamp': 20240101}, 'start_timestamp must be an ISO 8601 date and time'),
    ({'num_instances': 2, 'run_id': 'baseline'}, 'run_id must be an integer'),
    ({'num_instances': 0}, 'num_instances must be between'),
    ({'num_instances': 'many'}, 'num_instances must be an integer'),
])
def test_invalid_request_is_a_400_and_does_not_touch_the_session(client, discovered, tiny_xes_path, data_files, body, message):
    session_id, _ = discovered(tiny_xes_path)

    response = client.post(f'/api/simulate/{session_id}', json=body)

    assert response.status_code == 400, response.data
    assert message in response.get_json()['error']
    assert _status(session_id) == 'ready'
    assert data_files()[1] == []


def test_empty_body_simulates_the_baseline_with_defaults(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)

    response = client.post(f'/api/simulate/{session_id}')

    assert response.status_code == 200, response.data
    assert response.get_json()['run']['is_baseline'] is True
    assert response.get_json()['run']['num_instances'] == 100
    assert _status(session_id) == 'completed'


@pytest.mark.parametrize("start", ['2024-03-04T10:00', '2024-03-04T10:00:00Z', '2024-03-04T10:00:00+05:00'])
def test_start_timestamp_is_the_wall_clock_of_the_calendars(client, discovered, tiny_xes_path, start):
    """An offset is dropped, not converted: 10:00 anywhere starts at 10 o'clock."""
    session_id, _ = discovered(tiny_xes_path)

    response = client.post(f'/api/simulate/{session_id}', json={'num_instances': 3, 'start_timestamp': start})
    assert response.status_code == 200, response.data

    csv = client.get(f"/api/download/{response.get_json()['sim_output_filename']}")
    df = pd.read_csv(io.BytesIO(csv.data), parse_dates=['enabled:timestamp'])
    assert df['enabled:timestamp'].min() >= pd.Timestamp('2024-03-04 10:00')
    assert df['enabled:timestamp'].min() < pd.Timestamp('2024-03-11 10:00')


def test_failed_simulation_restores_the_session(client, discovered, tiny_xes_path, data_files, monkeypatch):
    session_id, _ = discovered(tiny_xes_path)
    first = client.post(f'/api/simulate/{session_id}', json={'num_instances': 2}).get_json()
    assert _status(session_id) == 'completed'

    def boom(self, *args, **kwargs):
        raise RuntimeError('simulator exploded at /secret/path.py')

    with monkeypatch.context() as patch:
        patch.setattr(prosit_integration.ProSiTIntegration, 'run_simulation', boom)
        response = client.post(f'/api/simulate/{session_id}', json={'num_instances': 2})

    assert response.status_code == 500
    body = response.get_json()
    assert body['error'] == 'Simulation failed' and len(body['error_id']) >= 16
    assert 'secret' not in response.get_data(as_text=True)

    # Not "error", not stuck on "simulating": the last good state.
    assert _status(session_id) == 'completed'
    # The previous simulation is still there, and nothing new was left behind.
    assert data_files()[1] == [first['sim_output_filename']]
    runs = client.get(f'/api/sessions/{session_id}/runs').get_json()['runs']
    assert runs[0]['simulation_df_filename'] == first['sim_output_filename']
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 2}).status_code == 200


def test_failed_first_simulation_leaves_the_session_ready(client, discovered, tiny_xes_path, monkeypatch):
    session_id, _ = discovered(tiny_xes_path)
    monkeypatch.setattr(
        prosit_integration.ProSiTIntegration, 'run_simulation',
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError('no')),
    )

    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 2}).status_code == 500
    assert _status(session_id) == 'ready'


def test_results_of_a_run_that_is_not_a_number_are_a_400(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)
    client.post(f'/api/simulate/{session_id}', json={'num_instances': 2})

    for url in (f'/api/get_visualization/{session_id}/case_duration_dist', f'/api/get_activities_and_resources/{session_id}'):
        response = client.get(f'{url}?run_id=latest')
        assert response.status_code == 400, url
        assert 'run_id must be an integer' in response.get_json()['error']
        assert client.get(f'{url}?run_id=9999').status_code == 404
        assert client.get(url).status_code == 200
