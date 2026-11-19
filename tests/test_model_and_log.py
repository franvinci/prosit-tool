"""A Petri net and an event log that do not go together: what is sent, what is refused, what is said."""

import pandas as pd
import pm4py
import pytest
from pm4py.objects.petri_net.obj import PetriNet

from prosit_tool.extensions import db
from prosit_tool.models import SimulationSession
from prosit_tool.prosit_integration import ProSiTIntegration, activities_outside_model, listed

from .conftest import event_rows


def net_of(activities, path):
    """A PNML file with the model of a log in which every case runs ``activities`` in order."""
    log = pm4py.convert_to_event_log(pd.DataFrame(event_rows(activities=activities, cases=4)))
    net, initial, final = pm4py.discover_petri_net_inductive(log)
    pm4py.write_pnml(net, initial, final, str(path))
    return path


@pytest.fixture
def another_process(tmp_path):
    """The model of a process that shares no activity with the logs of these tests."""
    return net_of(('Register', 'Check', 'Decide'), tmp_path / 'another.pnml')


# --- which Petri net the upload uses -----------------------------------------------------------

def test_net_that_comes_along_is_not_used_when_the_model_is_to_be_discovered(upload, tiny_xes_path, another_process,
                                                                           data_files):
    """The form keeps a file chosen earlier; "Discover from Event Log" must not import it."""
    response = upload(tiny_xes_path, another_process, petriNetSource='discover')

    assert response.status_code == 200, response.data
    body = response.get_json()
    assert body['pnml_filename'] is None
    assert data_files() == ([body['filename']], [])
    assert (db.session.get(SimulationSession, body['session_id']).get_parameters() or {}).get('pnml_filename') is None


def test_importing_uses_the_net(upload, tiny_xes_path, small_pnml_path):
    body = upload(tiny_xes_path, small_pnml_path, petriNetSource='import').get_json()

    assert body['pnml_filename'].endswith('.pnml')


def test_importing_needs_a_net(upload, tiny_xes_path, data_files):
    response = upload(tiny_xes_path, petriNetSource='import')

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Choose the PNML file of the Petri net to import'
    assert data_files() == ([], [])


def test_a_client_that_does_not_say_imports_the_net_it_sends(upload, tiny_xes_path, small_pnml_path):
    """The field is the one of the form: scripts that send a net mean to use it."""
    assert upload(tiny_xes_path, small_pnml_path).get_json()['pnml_filename'].endswith('.pnml')
    assert upload(tiny_xes_path).get_json()['pnml_filename'] is None


def test_unknown_source_is_refused(upload, tiny_xes_path):
    response = upload(tiny_xes_path, petriNetSource='guess')

    assert response.status_code == 400
    assert "petriNetSource must be 'discover' or 'import'" in response.get_json()['error']


# --- a net that is not the model of the log ---------------------------------------------------------

def test_net_of_another_process_is_refused_before_anything_long(client, upload, tiny_xes_path, another_process,
                                                               data_files, monkeypatch):
    def measured(*args, **kwargs):
        raise AssertionError('fitness was measured on a net that cannot replay the log')

    monkeypatch.setattr('prosit_tool.prosit_integration.fitness_evaluator.apply', measured)
    uploaded = upload(tiny_xes_path, another_process).get_json()

    response = client.post(f"/api/discover/{uploaded['session_id']}")

    assert response.status_code == 422, response.data
    error = response.get_json()['error']
    assert error.startswith('The Petri net cannot be used with this event log. '
                            'None of the activities of the event log is in the Petri net')
    assert 'Activities of the log: A, B, C, D.' in error
    assert 'Activities of the net: Check, Decide, Register.' in error
    assert 'DataFrame' not in error                      # what the library said when it got that far
    # nothing is left behind, and the session says what happened
    assert data_files() == (sorted([uploaded['filename'], uploaded['pnml_filename']]), [])
    db.session.expire_all()
    assert db.session.get(SimulationSession, uploaded['session_id']).status == 'error'
    assert client.get(f"/api/discover/{uploaded['session_id']}/progress").get_json()['in_progress'] is False


def test_activities_the_net_lacks_are_named_with_their_events(discovered, tiny_xes_path, tmp_path):
    """The log runs A, B, C, D; the net knows A, B, C: the events of D cannot be replayed."""
    _, body = discovered(tiny_xes_path, pnml_path=net_of(('A', 'B', 'C'), tmp_path / 'abc.pnml'))

    notes = [warning for warning in body['warnings'] if 'not in the process model' in warning]
    assert len(notes) == 1
    assert notes[0].endswith('nothing like them is simulated: D (5 events).')
    assert sorted(body['parameters']['process_model']['activities']) == ['A', 'B', 'C']


def test_a_net_with_every_activity_of_the_log_needs_no_note(discovered, tiny_xes_path):
    _, body = discovered(tiny_xes_path)

    assert not [warning for warning in body['warnings'] if 'not in the process model' in warning]


def test_activities_the_miner_took_for_noise_are_named(monkeypatch):
    """The miner may leave a rare activity out of the model (it does on real logs)."""
    usual = pm4py.convert_to_event_log(pd.DataFrame(event_rows(activities=('A', 'B', 'C'), cases=6)))
    without_the_rare_one = pm4py.discover_petri_net_inductive(usual)
    monkeypatch.setattr('prosit_tool.prosit_integration.pm4py.discover_petri_net_inductive',
                        lambda log, noise_threshold: without_the_rare_one)
    rows = event_rows(activities=('A', 'B', 'C'), cases=6)
    rare = rows[1].copy()
    rare.update({'concept:name': 'Odd one out'})
    rows.insert(2, rare)
    integration = ProSiTIntegration()
    integration.event_log = pm4py.convert_to_event_log(pd.DataFrame(rows))

    integration.discover_process_model(noise_threshold=0.2)

    assert integration.model_warnings == [
        'These activities of the event log are not in the process model, so their events are left out '
        'of what is learnt and nothing like them is simulated: Odd one out (1 event).'
    ]


def test_what_the_library_says_comes_with_the_lead(client, upload, tiny_xes_path, tmp_path, monkeypatch):
    """When prosit-pm gives up, the activities missing from the net are the first thing to look at."""
    def give_up(self, log, **options):
        raise ValueError('Cannot set a DataFrame with multiple columns to the single column execution_time')

    monkeypatch.setattr('prosit_tool.prosit_integration.SimulatorParameters.discover_from_eventlog', give_up)
    uploaded = upload(tiny_xes_path, net_of(('A', 'B', 'C'), tmp_path / 'abc.pnml')).get_json()

    response = client.post(f"/api/discover/{uploaded['session_id']}")

    assert response.status_code == 422
    error = response.get_json()['error']
    assert error.startswith('Parameter discovery failed. ValueError: Cannot set a DataFrame')
    assert error.endswith('nothing like them is simulated: D (5 events).')


# --- the pieces ------------------------------------------------------------------------------------------

def test_events_are_counted_per_activity_the_net_lacks():
    net = PetriNet('net')
    for name, label in (('t1', 'A'), ('t2', 'B'), ('skip', None)):
        net.transitions.add(PetriNet.Transition(name, label))
    log = pm4py.convert_to_event_log(pd.DataFrame(event_rows(activities=('A', 'X', 'B', 'X'), cases=3)))

    labels, events, outside = activities_outside_model(log, net)

    assert labels == {'A', 'B'}                          # the silent transition has none
    assert events == {'A': 3, 'B': 3, 'X': 6}
    assert outside == {'X': 6}


def test_long_lists_are_cut_short():
    assert listed([]) == '(none)'
    assert listed(['a', 'b']) == 'a, b'
    assert listed(range(12), limit=3) == '0, 1, 2 and 9 more'


def test_a_log_and_a_net_with_nothing_in_common_through_the_library(tiny_xes_path, another_process):
    """What happens without the check: prosit-pm fails on a frame with no row, far from the cause."""
    from prosit.simulator import SimulatorParameters

    from prosit_tool.api._shared import load_event_log

    log, _ = load_event_log(str(tiny_xes_path))
    net, initial, final = pm4py.read_pnml(str(another_process))

    with pytest.raises(Exception) as failure:
        SimulatorParameters(net, initial, final).discover_from_eventlog(log, max_depth_tree=0, verbose=False)

    # If a later prosit-pm handles this by itself, this test says so and the check can go.
    assert 'activit' not in str(failure.value).lower()
