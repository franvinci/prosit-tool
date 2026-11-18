"""What the page reads to draw itself: the list of sessions, and what the
parameters say about the model besides its numbers."""

import pm4py
import pytest
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.petri_net.utils import petri_utils

from .conftest import event_rows, write_xes


# --- the list of sessions -------------------------------------------------------------

def test_page_carries_no_session_of_its_own(client, discovered, tiny_xes_path):
    """The list is loaded by the page: what is on screen is what the server has now."""
    discovered(tiny_xes_path)

    page = client.get('/').get_data(as_text=True)

    assert 'id="sessionsList"' in page
    assert 'recent-session-item' not in page


def test_no_sessions(client):
    assert client.get('/api/sessions').get_json() == {'success': True, 'sessions': []}


def test_sessions_are_listed_with_what_the_list_shows(client, discovered, upload, tiny_xes_path):
    first, _ = discovered(tiny_xes_path)
    second = upload(tiny_xes_path).get_json()['session_id']           # uploaded, never discovered
    client.post(f'/api/sessions/{first}/runs', json={'name': 'Scenario'})
    client.post(f'/api/simulate/{first}', json={'num_instances': 2})  # the session used last

    sessions = client.get('/api/sessions').get_json()['sessions']

    assert [session['id'] for session in sessions] == [first, second]
    assert sessions[0]['label'] == sessions[1]['label'] == 'tiny'
    assert (sessions[0]['status'], sessions[0]['run_count']) == ('completed', 2)
    assert (sessions[1]['status'], sessions[1]['run_count']) == ('uploaded', 0)
    # UTC, and said to be: the browser turns it into local time.
    assert sessions[0]['last_used_at'].endswith('Z') and 'T' in sessions[0]['last_used_at']


def test_a_renamed_session_is_listed_under_its_new_name(client, upload, tiny_xes_path):
    session_id = upload(tiny_xes_path).get_json()['session_id']
    client.patch(f'/api/sessions/{session_id}', json={'display_name': 'March <b>'})

    assert client.get('/api/sessions').get_json()['sessions'][0]['label'] == 'March <b>'


def test_only_the_most_recent_sessions_are_listed(client, upload, tiny_xes_path):
    ids = [upload(tiny_xes_path).get_json()['session_id'] for _ in range(17)]

    listed = [session['id'] for session in client.get('/api/sessions').get_json()['sessions']]

    assert len(listed) == 15
    assert set(listed) <= set(ids)


# --- what the parameters say about the model --------------------------------------------

def test_parameters_say_how_the_model_was_discovered(client, discovered, tiny_xes_path):
    _, plain = discovered(tiny_xes_path)
    _, rules = discovered(tiny_xes_path, '?max_depth_tree=1&use_workload_features=1')

    assert plain['parameters']['model_options'] == {'rules_mode': False, 'use_workload_features': False}
    assert rules['parameters']['model_options'] == {'rules_mode': True, 'use_workload_features': True}


def test_model_options_are_shown_not_stored(client, discovered, tiny_xes_path):
    """Sent back with a scenario, they change nothing of how it is simulated."""
    session_id, body = discovered(tiny_xes_path)
    parameters = dict(body['parameters'], model_options={'rules_mode': True, 'use_workload_features': True})

    run_id = client.post(f'/api/sessions/{session_id}/runs',
                         json={'name': 'Scenario', 'parameters': parameters}).get_json()['run']['id']

    stored = client.get(f'/api/runs/{run_id}').get_json()['parameters']['model_options']
    assert stored == {'rules_mode': False, 'use_workload_features': False}


@pytest.fixture
def net_with_a_silent_transition(tmp_path):
    """A -> (B or a silent skip) -> C, where the silent transition has a name of its own."""
    net = PetriNet('net')
    places = [PetriNet.Place(name) for name in ('start', 'p1', 'p2', 'end')]
    transitions = [
        PetriNet.Transition('A', 'A'),
        PetriNet.Transition('B', 'B'),
        PetriNet.Transition('skip_B', None),
        PetriNet.Transition('C', 'C'),
    ]
    for place in places:
        net.places.add(place)
    for transition in transitions:
        net.transitions.add(transition)
    start, p1, p2, end = places
    a, b, skip, c = transitions
    for source, target in ((start, a), (a, p1), (p1, b), (b, p2), (p1, skip), (skip, p2), (p2, c), (c, end)):
        petri_utils.add_arc_from_to(source, target, net)
    path = tmp_path / 'net.pnml'
    pm4py.write_pnml(net, Marking({start: 1}), Marking({end: 1}), str(path))
    return path


def test_silent_transitions_are_named(client, discovered, tmp_path, net_with_a_silent_transition):
    """A visible transition whose label equals its name must not be taken for a silent one."""
    log = write_xes(event_rows(activities=('A', 'B', 'C'), cases=6), tmp_path / 'abc.xes')

    session_id, body = discovered(log, pnml_path=net_with_a_silent_transition)

    model = body['parameters']['process_model']
    assert model['silent_transitions'] == ['skip_B']
    assert sorted(model['activities']) == ['A', 'B', 'C']
    # the same when the session is opened again
    reloaded = client.get(f'/api/parameters/{session_id}').get_json()['parameters']['process_model']
    assert reloaded['silent_transitions'] == ['skip_B']


# --- optional columns left out on purpose --------------------------------------------------

def test_optional_column_left_out_is_not_taken_from_the_log_anyway(client, discovered, tmp_path):
    """"(none)" for the resource of an XES that has org:resource: no resources."""
    path = write_xes(event_rows(cases=6), tmp_path / 'log.xes')
    mapping = {'case_id_col': 'case:concept:name', 'activity_col': 'concept:name', 'end_ts_col': 'time:timestamp'}

    _, with_resources = discovered(path, start_ts_col='start:timestamp', resource_col='org:resource', **mapping)
    _, without = discovered(path, start_ts_col='start:timestamp', resource_col='', **mapping)

    assert sorted(with_resources['parameters']['resource_params']['resources']) == ['r1', 'r2']
    assert without['parameters']['resource_params']['resources'] == ['unknown']
    assert any('no resources' in warning for warning in without['warnings'])


def test_optional_column_not_mentioned_is_used_as_before(client, discovered, tmp_path):
    """A client that does not send the field at all keeps the standard columns."""
    path = write_xes(event_rows(cases=6), tmp_path / 'log.xes')

    _, body = discovered(path, case_id_col='case:concept:name', activity_col='concept:name',
                         end_ts_col='time:timestamp')

    assert sorted(body['parameters']['resource_params']['resources']) == ['r1', 'r2']
    assert body['warnings'] == []


def test_csv_column_with_a_standard_name_can_be_left_out_too(client, discovered, tmp_path):
    lines = ['Case,Task,Done,start:timestamp,org:resource']
    for case in range(6):
        for position, task in enumerate(('A', 'B', 'C')):
            hour = 8 + position
            lines.append(f'{case},{task},2024-01-0{case + 1} {hour}:30:00,2024-01-0{case + 1} {hour}:00:00,w{position % 2}')
    path = tmp_path / 'log.csv'
    path.write_text('\n'.join(lines) + '\n')

    _, body = discovered(path, case_id_col='Case', activity_col='Task', end_ts_col='Done',
                         start_ts_col='', resource_col='')

    assert body['parameters']['resource_params']['resources'] == ['unknown']
    assert any('no start timestamps' in warning for warning in body['warnings'])
