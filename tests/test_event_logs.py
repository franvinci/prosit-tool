"""Event logs that lack what prosit-pm reads from every event.

Many real logs have only the completion timestamp, or no resource. They are
made usable instead of rejected, and the user is told what that implies.
"""

import pandas as pd
import pm4py
import pytest

from prosit_tool.api._shared import UNKNOWN_RESOURCE, EventLogError, normalize_event_log

from .conftest import event_rows, write_xes


def _log(rows):
    return pm4py.convert_to_event_log(pd.DataFrame(rows))


# --- normalize_event_log --------------------------------------------------------------

def test_complete_log_is_left_alone():
    log, notes = normalize_event_log(_log(event_rows()))

    assert notes == []
    assert {event['org:resource'] for trace in log for event in trace} == {'r1', 'r2'}


def test_missing_start_timestamps_become_the_end_timestamps():
    log, notes = normalize_event_log(_log(event_rows(with_start=False)))

    assert all(event['start:timestamp'] == event['time:timestamp'] for trace in log for event in trace)
    assert len(notes) == 1 and 'no start timestamps' in notes[0] and 'instantaneous' in notes[0]


def test_missing_resources_become_one_named_resource():
    log, notes = normalize_event_log(_log(event_rows(resources=None)))

    assert {event['org:resource'] for trace in log for event in trace} == {UNKNOWN_RESOURCE}
    assert len(notes) == 1 and 'no resources' in notes[0] and 'max concurrency' in notes[0]


def test_partly_missing_values_are_counted():
    rows = event_rows()
    for row in rows[:3]:
        del row['start:timestamp']
    rows[5]['org:resource'] = None
    rows[6]['org:resource'] = '   '

    log, notes = normalize_event_log(_log(rows))

    assert notes == [
        '3 of 20 events have no start timestamp: for them the end timestamp is used as the start.',
        f'2 of 20 events have no resource: they were assigned to a resource named "{UNKNOWN_RESOURCE}".',
    ]
    resources = [event['org:resource'] for trace in log for event in trace]
    assert resources.count(UNKNOWN_RESOURCE) == 2


def test_log_without_events_is_refused():
    with pytest.raises(EventLogError, match='contains no events'):
        normalize_event_log(pm4py.objects.log.obj.EventLog())


# --- through the API ------------------------------------------------------------------

def test_xes_without_start_timestamps_and_resources_can_be_simulated(client, discovered, tmp_path):
    path = write_xes(event_rows(with_start=False, resources=None, cases=8), tmp_path / 'bare.xes')

    session_id, body = discovered(path)

    assert len(body['warnings']) == 2
    assert 'no start timestamps' in body['warnings'][0]
    assert 'no resources' in body['warnings'][1]
    assert body['parameters']['resource_params']['resources'] == [UNKNOWN_RESOURCE]

    simulate = client.post(f'/api/simulate/{session_id}', json={'num_instances': 5})
    assert simulate.status_code == 200, simulate.data
    assert simulate.get_json()['num_events'] == 20

    metrics = client.post(f'/api/metrics/{session_id}')
    assert metrics.status_code == 200, metrics.data


def test_empty_xes_is_refused_with_a_reason(client, upload, tmp_path):
    path = tmp_path / 'empty.xes'
    pm4py.write_xes(pm4py.objects.log.obj.EventLog(), str(path))
    session_id = upload(path).get_json()['session_id']

    response = client.post(f'/api/discover/{session_id}')

    assert response.status_code == 422, response.data
    assert response.get_json()['error'] == 'The event log cannot be used. The event log contains no events.'


CSV_HEADER = 'Case,Task,Done,Began,Who\n'


def _csv(tmp_path, body, name='log.csv'):
    path = tmp_path / name
    path.write_text(CSV_HEADER + body)
    return path


def _csv_rows(with_who=True):
    lines = []
    base = pd.Timestamp('2024-01-01 08:00')
    for case in range(6):
        for position, task in enumerate(('A', 'B', 'C')):
            begin = base + pd.Timedelta(hours=case * 3 + position)
            who = f'w{position % 2}' if with_who else ''
            lines.append(f'{case},{task},{begin + pd.Timedelta(minutes=20)},{begin},{who}')
    return '\n'.join(lines) + '\n'


def test_csv_needs_only_case_activity_and_end_timestamp(client, discovered, tmp_path):
    path = _csv(tmp_path, _csv_rows())

    session_id, body = discovered(path, case_id_col='Case', activity_col='Task', end_ts_col='Done')

    assert sorted(body['process_model']['activities']) == ['A', 'B', 'C']
    assert 'no start timestamps' in body['warnings'][0]
    assert 'no resources' in body['warnings'][1]
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 4}).status_code == 200


def test_csv_with_every_column_mapped_has_no_warnings(client, discovered, tmp_path):
    path = _csv(tmp_path, _csv_rows())

    _, body = discovered(path, case_id_col='Case', activity_col='Task', end_ts_col='Done',
                         start_ts_col='Began', resource_col='Who')

    assert body['warnings'] == []
    assert sorted(body['parameters']['resource_params']['resources']) == ['w0', 'w1']


def test_csv_timestamps_finer_than_microseconds_can_be_read_back(client, discovered, tmp_path):
    """Written with nine decimals, pm4py on Python 3.10 would lose every timestamp."""
    lines = []
    base = pd.Timestamp('2024-01-01 08:00:00.123456789')
    for case in range(6):
        for position, task in enumerate(('A', 'B', 'C')):
            begin = base + pd.Timedelta(hours=case * 3 + position)
            lines.append(f'{case},{task},{begin + pd.Timedelta(minutes=20)},{begin},w{position % 2}')
    assert lines[0].count('.123456789') == 2
    path = _csv(tmp_path, '\n'.join(lines) + '\n')

    session_id, body = discovered(path, case_id_col='Case', activity_col='Task', end_ts_col='Done',
                                  start_ts_col='Began', resource_col='Who')

    assert body['warnings'] == []
    assert sorted(body['process_model']['activities']) == ['A', 'B', 'C']
    assert client.post(f'/api/simulate/{session_id}', json={'num_instances': 3}).status_code == 200


def test_csv_with_empty_resource_cells_has_no_resource_called_nan(client, discovered, tmp_path):
    lines = _csv_rows().splitlines()
    lines[0] = lines[0].rsplit(',', 1)[0] + ','      # first event: resource cell left empty
    path = _csv(tmp_path, '\n'.join(lines) + '\n')

    _, body = discovered(path, case_id_col='Case', activity_col='Task', end_ts_col='Done',
                         start_ts_col='Began', resource_col='Who')

    resources = body['parameters']['resource_params']['resources']
    assert 'nan' not in resources
    assert sorted(resources) == sorted([UNKNOWN_RESOURCE, 'w0', 'w1'])


@pytest.mark.parametrize("form, message", [
    ({'case_id_col': 'Case', 'activity_col': 'Task'}, 'Column mapping incomplete: end_ts_col'),
    ({'activity_col': 'Task', 'end_ts_col': 'Done'}, 'Column mapping incomplete: case_id_col'),
    ({}, 'CSV upload requires column mapping'),
    ({'case_id_col': 'Case', 'activity_col': 'Task', 'end_ts_col': 'Finished'}, 'CSV does not contain column(s): Finished'),
])
def test_csv_mapping_errors(upload, tmp_path, form, message):
    response = upload(_csv(tmp_path, _csv_rows()), **form)

    assert response.status_code == 400, response.data
    assert response.get_json()['error'] == message


def test_csv_rows_without_end_timestamp_are_reported(upload, tmp_path, data_files):
    lines = _csv_rows().splitlines()
    parts = lines[2].split(',')
    parts[2] = ''
    lines[2] = ','.join(parts)

    response = upload(_csv(tmp_path, '\n'.join(lines) + '\n'),
                      case_id_col='Case', activity_col='Task', end_ts_col='Done')

    assert response.status_code == 400, response.data
    assert response.get_json()['error'] == 'CSV has 1 row(s) with no end timestamp'
    assert data_files() == ([], [])  # the rejected upload leaves no file
