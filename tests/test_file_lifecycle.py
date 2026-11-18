"""Files of sessions and scenarios: unique names, and nothing left behind."""

import os
import time

import pytest

from prosit_tool import prosit_integration
from prosit_tool.api import _shared
from prosit_tool.extensions import db
from prosit_tool.models import SimulationRun


@pytest.fixture
def frozen_clock(monkeypatch):
    """Every request of the test happens in the same second."""
    monkeypatch.setattr(_shared.time, 'time', lambda: 1_900_000_000.0)
    monkeypatch.setattr(_shared, '_last_stamp', 0)


def test_uploads_in_the_same_second_get_different_files(client, upload, tiny_xes_path, data_files, frozen_clock):
    first = upload(tiny_xes_path).get_json()
    second = upload(tiny_xes_path).get_json()

    assert first['filename'] != second['filename']
    assert data_files()[0] == sorted([first['filename'], second['filename']])

    # Deleting one session must not take the other one's log with it.
    assert client.delete(f"/api/sessions/{first['session_id']}").status_code == 200
    assert data_files()[0] == [second['filename']]
    assert client.post(f"/api/discover/{second['session_id']}").status_code == 200


def test_discoveries_in_the_same_second_get_different_files(client, upload, tiny_xes_path, app, frozen_clock):
    sessions = [upload(tiny_xes_path).get_json()['session_id'] for _ in range(2)]

    bodies = [client.post(f'/api/discover/{sid}').get_json() for sid in sessions]

    assert bodies[0]['json_filename'] != bodies[1]['json_filename']
    names = os.listdir(app.config['UPLOAD_FOLDER'])
    assert len(names) == len(set(names)) == 6  # 2 logs, 2 models, 2 parameter files

    # Each session simulates from its own parameters and keeps its own log.
    outputs = [
        client.post(f'/api/simulate/{sid}', json={'num_instances': 2}).get_json()['sim_output_filename']
        for sid in sessions
    ]
    assert outputs[0] != outputs[1]
    assert client.delete(f'/api/sessions/{sessions[0]}').status_code == 200
    assert client.get(f'/api/parameters/{sessions[1]}').status_code == 200
    assert client.get(f'/api/download/{outputs[1]}').status_code == 200


def test_unique_timestamp_never_repeats_and_skips_names_in_use(app, frozen_clock):
    with app.app_context():
        with open(os.path.join(app.config['UPLOAD_FOLDER'], '1900000001_old.xes'), 'w'):
            pass
        with open(os.path.join(app.config['SIMULATION_FOLDER'], 'simulation_1900000003_s1_r1.csv'), 'w'):
            pass

        stamps = [_shared.unique_timestamp() for _ in range(4)]

    assert stamps == [1_900_000_000, 1_900_000_002, 1_900_000_004, 1_900_000_005]


def test_unique_timestamp_follows_the_clock(app, monkeypatch):
    # The counter only runs ahead of the clock when more than one name per
    # second has been handed out, as earlier tests of this process have done.
    monkeypatch.setattr(_shared, '_last_stamp', 0)
    with app.app_context():
        first = _shared.unique_timestamp()
        second = _shared.unique_timestamp()
    assert second > first
    assert abs(first - time.time()) < 5


def test_rediscovery_replaces_the_baseline_files(client, discovered, tiny_xes_path, data_files):
    session_id, first = discovered(tiny_xes_path)
    scenario = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Scenario'}).get_json()['run']
    simulation = client.post(f'/api/simulate/{session_id}', json={'num_instances': 2}).get_json()
    scenario_snapshot = db.session.get(SimulationRun, scenario['id']).parameters_filename

    second = client.post(f'/api/discover/{session_id}?max_depth_tree=1')
    assert second.status_code == 200, second.data
    second = second.get_json()

    uploads, simulations = data_files()
    assert second['json_filename'] != first['json_filename']
    assert first['json_filename'] not in uploads           # old baseline parameters: gone
    assert second['json_filename'] in uploads
    assert scenario_snapshot in uploads                    # the what-if keeps its own copy
    assert simulation['sim_output_filename'] not in simulations  # stale baseline simulation: gone
    assert len(uploads) == 4  # log, model, baseline parameters, scenario parameters

    runs = {run['name']: run for run in client.get(f'/api/sessions/{session_id}/runs').get_json()['runs']}
    assert runs['As-Is']['has_simulation'] is False
    assert client.get(f"/api/runs/{scenario['id']}").status_code == 200


def test_new_simulation_replaces_the_previous_log(client, discovered, tiny_xes_path, data_files):
    session_id, _ = discovered(tiny_xes_path)

    first = client.post(f'/api/simulate/{session_id}', json={'num_instances': 2}).get_json()['sim_output_filename']
    second = client.post(f'/api/simulate/{session_id}', json={'num_instances': 3}).get_json()['sim_output_filename']

    assert first != second
    assert data_files()[1] == [second]
    assert client.get(f'/api/download/{first}').status_code == 404
    assert client.get(f'/api/get_visualization/{session_id}/case_duration_dist').status_code == 200


def test_deleting_scenarios_and_sessions_leaves_no_files(client, discovered, tiny_xes_path, data_files):
    session_id, _ = discovered(tiny_xes_path)
    run_id = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Scenario'}).get_json()['run']['id']
    client.post(f'/api/simulate/{session_id}', json={'num_instances': 2})
    client.post(f'/api/runs/{run_id}/simulate', json={'num_instances': 2})
    assert len(data_files()[0]) == 4 and len(data_files()[1]) == 2

    assert client.delete(f'/api/runs/{run_id}').status_code == 200
    assert len(data_files()[0]) == 3 and len(data_files()[1]) == 1

    assert client.delete(f'/api/sessions/{session_id}').status_code == 200
    assert data_files() == ([], [])


def test_failed_discovery_leaves_only_the_uploaded_log(client, upload, tiny_xes_path, data_files, monkeypatch):
    uploaded = upload(tiny_xes_path).get_json()

    def boom(self, *args, **kwargs):
        raise RuntimeError('cannot save')

    # Fail as late as possible: after the model has been mined and drawn.
    monkeypatch.setattr(prosit_integration.ProSiTIntegration, 'save_parameters_to_json', boom)
    response = client.post(f"/api/discover/{uploaded['session_id']}")

    assert response.status_code == 500
    assert data_files() == ([uploaded['filename']], [])


def test_failed_rediscovery_keeps_the_previous_one_usable(client, discovered, tiny_xes_path, data_files, monkeypatch):
    session_id, first = discovered(tiny_xes_path)
    files_before = data_files()

    with monkeypatch.context() as patch:
        patch.setattr(
            prosit_integration.SimulatorParameters, 'discover_from_eventlog',
            lambda self, *a, **k: (_ for _ in ()).throw(ValueError('nothing to learn')),
        )
        assert client.post(f'/api/discover/{session_id}').status_code == 422

    assert data_files() == files_before
    assert client.get(f'/api/parameters/{session_id}').get_json()['json_filename'] == first['json_filename']
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 2}).status_code == 200
