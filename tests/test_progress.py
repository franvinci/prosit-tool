"""How far a discovery has got: the tracker, what it reads, and what the page is told."""

import json
import os
import sys
import threading
import time
import urllib.request

import pytest

from prosit_tool import progress
from prosit_tool.progress import Bar, LibraryOutput, Progress, Step, track, watch_output
from prosit_tool.prosit_integration import LIBRARY_STEPS, DiscoveryError, ProSiTIntegration, discovery_steps

from .conftest import event_rows, write_xes
from .test_cli import HOST, live_prosit

# What the libraries really write (pm4py 2.7, prosit-pm 1.0.5, tqdm 4).
PM4PY_BAR = '\raligning log, completed variants ::  83%|████████▎ | 506/608 [00:00<00:00, 2556.96it/s]'
PROSIT_BAR = '\rmodel fitting:   2%|▏         | 1/50 [00:02<01:52,  2.30s/it]'
NAMELESS_BAR = '\r100%|██████████| 608/608 [00:00<00:00, 11588.05it/s]'
ASCII_BAR = '\rmodel fitting:  45%|####5     | 45/100 [00:01<00:01, 30.1it/s]'


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def plan():
    return [
        Step('first', 'Doing the first thing', 1),
        Step('second', 'Doing the second thing', 2, (Bar(unit='items'),)),
        Step('third', 'Doing the third thing', 1),
    ]


# --- where a plan has got ----------------------------------------------------------------

def test_it_begins_at_the_first_step():
    clock = Clock()
    report = Progress(plan(), clock=clock).snapshot()

    assert report == {
        'in_progress': True, 'percent': 0.0, 'step': 1, 'steps': 3,
        'label': 'Doing the first thing', 'message': 'Doing the first thing', 'elapsed': 0.0,
    }
    json.dumps(report)


def test_a_step_that_begins_closes_the_ones_before_it():
    followed = Progress(plan())

    followed.start('second')
    assert (followed.snapshot()['step'], followed.snapshot()['percent']) == (2, 25.0)

    followed.start('third')
    assert (followed.snapshot()['step'], followed.snapshot()['percent']) == (3, 75.0)


def test_a_step_may_be_skipped():
    followed = Progress(plan())

    followed.start('third')

    assert followed.snapshot()['label'] == 'Doing the third thing'
    assert followed.snapshot()['percent'] == 75.0


def test_steps_only_move_forward():
    followed = Progress(plan())
    followed.start('third')

    followed.start('first')
    followed.start('not in the plan')

    assert followed.snapshot()['step'] == 3


def test_a_plan_needs_a_step():
    with pytest.raises(ValueError):
        Progress([])


def test_a_bar_moves_the_step_within_its_share():
    followed = Progress(plan())
    followed.start('second')

    followed.bar('counting', 50, 5, 10)

    report = followed.snapshot()
    assert report['percent'] == 50.0                       # 25 before it, half of its 50
    assert (report['done'], report['total'], report['unit']) == (5, 10, 'items')
    assert report['message'] == 'Doing the second thing (5 of 10 items)'


def test_the_bar_says_what_it_counts_when_it_knows():
    followed = Progress(plan())
    followed.start('second')

    followed.bar('counting', 50, 5, 10, 'variants')

    assert followed.snapshot()['unit'] == 'variants'


def test_a_bar_without_a_total_moves_the_step_but_counts_nothing():
    followed = Progress(plan())
    followed.start('second')

    followed.bar('counting', 50)

    report = followed.snapshot()
    assert report['percent'] == 50.0
    assert 'total' not in report and report['message'] == 'Doing the second thing'


def test_the_bars_of_a_step_follow_one_another():
    followed = Progress([Step('only', 'Working', 1, (Bar(0.8, 'variants'), Bar(0.2, 'traces'))), Step('end', 'Ending', 1)])

    followed.bar('aligning', 100, 9, 9)
    assert followed.snapshot()['percent'] == 40.0          # 80% of half the plan

    followed.bar('', 50, 3, 6)
    report = followed.snapshot()
    assert report['percent'] == 45.0
    assert (report['done'], report['total'], report['unit']) == (3, 6, 'traces')


def test_a_bar_that_starts_over_is_the_next_one():
    followed = Progress([Step('only', 'Working', 1, (Bar(0.5), Bar(0.5))), Step('end', 'Ending', 1)])
    followed.bar('aligning', 0)
    followed.bar('aligning', 90)

    followed.bar('aligning', 10)          # same name, back to the start

    assert followed.snapshot()['percent'] == 27.5


def test_a_bar_the_step_is_not_known_to_draw_leaves_it_where_it_is():
    followed = Progress(plan())
    followed.start('second')
    followed.bar('counting', 100, 10, 10)

    followed.bar('something else', 30, 3, 10)

    report = followed.snapshot()
    assert report['percent'] == 75.0
    assert (report['done'], report['total']) == (10, 10)


def test_it_never_goes_back():
    followed = Progress(plan())
    seen = []
    for move in (
        lambda: followed.bar('a', 40), lambda: followed.bar('a', 20), lambda: followed.start('second'),
        lambda: followed.bar('b', 70, 7, 10), lambda: followed.bar('c', 5), lambda: followed.start('first'),
        lambda: followed.start('third'), lambda: followed.bar('d', 100),
    ):
        move()
        seen.append(followed.snapshot()['percent'])

    assert seen == sorted(seen)


def test_it_is_not_over_until_the_answer_arrives():
    followed = Progress(plan())
    followed.start('third')

    followed.bar('last', 100, 4, 4)

    assert followed.snapshot()['percent'] == 99.0


def test_a_note_is_shown_until_the_next_step():
    followed = Progress(plan())

    followed.note('Something new')
    assert followed.snapshot()['label'] == 'Something new'
    assert followed.snapshot()['step'] == 1

    followed.start('second')
    assert followed.snapshot()['label'] == 'Doing the second thing'


def test_time_is_counted_from_the_start():
    clock = Clock()
    followed = Progress(plan(), clock=clock)

    clock.now += 83.26

    assert followed.snapshot()['elapsed'] == 83.3


# --- what the libraries write ----------------------------------------------------------------

@pytest.mark.parametrize('text, expected', [
    (PM4PY_BAR, ('aligning log, completed variants', 83, 506, 608, 'variants')),
    (PROSIT_BAR, ('model fitting', 2, 1, 50, '')),
    (NAMELESS_BAR, ('', 100, 608, 608, '')),
    (ASCII_BAR, ('model fitting', 45, 45, 100, '')),
    ('\rparsing log, completed traces :: 100%|██████████| 2000/2000 [00:01<00:00, 1649.30it/s]\n',
     ('parsing log, completed traces', 100, 2000, 2000, 'traces')),
    ('\rdownloading:  12%|█▏        | 1.2k/10.0k [00:01<00:07]', ('downloading', 12, None, None, '')),
])
def test_a_progress_bar_is_read(text, expected):
    assert LibraryOutput._meter(text) == expected


@pytest.mark.parametrize('text', [
    'Resources discovery...\n', '15it [00:02, 7.1it/s]', 'done 100% of it', '', '\n',
])
def test_what_is_not_a_progress_bar_is_not_read_as_one(text):
    assert LibraryOutput._meter(text) is None


def read(announcements=None):
    followed = Progress(discovery_steps())
    return followed, LibraryOutput(followed, LIBRARY_STEPS if announcements is None else announcements)


def test_the_name_of_a_step_begins_it():
    followed, reader = read()

    reader('stdout', 'Feature discovery...\n')

    assert followed.snapshot()['label'] == 'Replaying the log on the model'


def test_print_writes_a_line_in_two_pieces():
    followed, reader = read()

    reader('stdout', 'Calendars discovery...')
    assert followed.snapshot()['step'] == 1
    reader('stdout', '\n')

    assert followed.snapshot()['label'] == 'Discovering the calendars'


def test_every_step_prosit_announces_is_in_the_plan():
    for incremental in (False, True):
        keys = {step.key for step in discovery_steps(incremental=incremental)}
        announced = {key for line, key in LIBRARY_STEPS.items()
                     if incremental or not line.startswith('Incremental')}
        assert announced - keys == ({'fitting'} if incremental else set())


def test_the_plan_depends_on_how_the_discovery_is_run():
    labels = lambda **how: [step.label for step in discovery_steps(**how)]  # noqa: E731

    assert 'Discovering the process model' in labels()
    assert 'Reading the Petri net' in labels(importing_model=True)
    assert 'Fitting the models' in labels() and 'Fitting the models' not in labels(incremental=True)
    weight = lambda **how: {step.key: step.weight for step in discovery_steps(**how)}['fitting']  # noqa: E731
    assert weight(rules=True) > weight()


def test_a_step_the_tool_has_not_heard_of_is_shown_as_the_library_names_it():
    followed, reader = read()
    reader('stdout', 'Feature discovery...\n')

    reader('stdout', 'Handover network discovery...\n')

    report = followed.snapshot()
    assert report['label'] == 'Handover network discovery'
    assert report['step'] == 7                          # still within the step it was in


def test_other_lines_change_nothing():
    followed, reader = read()
    before = followed.snapshot()['label']

    reader('stdout', 'Loaded 12 traces\n')
    reader('stderr', 'UserWarning: something to know\n')
    reader('stdout', '\n\n')

    assert followed.snapshot()['label'] == before


def test_a_bar_is_read_from_either_stream_and_moves_the_step():
    followed, reader = read()
    reader('stdout', 'Model fitting...\n')
    at_start = followed.snapshot()['percent']

    reader('stderr', ASCII_BAR)

    report = followed.snapshot()
    assert report['percent'] > at_start
    assert (report['done'], report['total'], report['unit']) == (45, 100, 'models')


def test_text_that_never_ends_a_line_is_not_kept_for_ever():
    followed, reader = read()

    for _ in range(200):
        reader('stdout', 'x' * 100)

    assert len(reader._unfinished['stdout']) <= 500


# --- listening to one thread ----------------------------------------------------------------

def test_what_the_thread_writes_is_heard_and_still_written(capsys):
    heard = []

    with watch_output(lambda stream, text: heard.append((stream, text))):
        print('to the console')
        sys.stderr.write('a warning\n')

    assert ('stdout', 'to the console') in heard and ('stderr', 'a warning\n') in heard
    captured = capsys.readouterr()
    assert captured.out == 'to the console\n' and captured.err == 'a warning\n'


def test_the_streams_are_given_back():
    out, err = sys.stdout, sys.stderr

    with watch_output(lambda stream, text: None):
        assert sys.stdout is not out and sys.stderr is not err
        assert sys.stdout.encoding == out.encoding       # everything else is the real stream's

    assert sys.stdout is out and sys.stderr is err


def test_the_streams_are_given_back_when_the_work_fails():
    out = sys.stdout

    with pytest.raises(RuntimeError):
        with watch_output(lambda stream, text: None):
            raise RuntimeError('the work failed')

    assert sys.stdout is out


def test_other_threads_are_not_heard():
    heard = []
    written = threading.Event()

    def other_request():
        print('from another request')
        written.set()

    with watch_output(lambda stream, text: heard.append(text)):
        thread = threading.Thread(target=other_request)
        thread.start()
        thread.join()
        print('mine')

    assert written.is_set()
    assert 'mine' in heard and 'from another request' not in heard


def test_two_requests_listen_at_the_same_time_each_to_itself():
    out = sys.stdout
    heard = {'a': [], 'b': []}
    both_in = threading.Barrier(2)
    release_a = threading.Event()

    def request(name, wait_for=None):
        with watch_output(lambda stream, text: heard[name].append(text)):
            both_in.wait(timeout=10)
            print(f'{name} works')
            if wait_for is not None:
                wait_for.wait(timeout=10)
            print(f'{name} still works')

    a = threading.Thread(target=request, args=('a', release_a))
    b = threading.Thread(target=request, args=('b',))
    a.start(), b.start()
    b.join(timeout=10)
    # b has left: a must still be heard.
    release_a.set()
    a.join(timeout=10)

    assert [text for text in heard['a'] if text.strip()] == ['a works', 'a still works']
    assert [text for text in heard['b'] if text.strip()] == ['b works', 'b still works']
    assert sys.stdout is out


def test_a_listener_that_fails_does_not_break_the_work(capsys):
    def listener(stream, text):
        raise ValueError('cannot read this')

    with watch_output(listener):
        print('the work goes on')

    assert capsys.readouterr().out == 'the work goes on\n'


def test_a_program_without_a_console_can_be_listened_to(monkeypatch):
    """A windowed executable has no stdout at all."""
    monkeypatch.setattr(sys, 'stdout', None)
    heard = []

    with watch_output(lambda stream, text: heard.append(text)):
        assert sys.stdout.write('nobody sees this') == len('nobody sees this')
        sys.stdout.flush()

    assert heard == ['nobody sees this']
    assert sys.stdout is None


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='worker processes are forked only on Linux')
def test_a_forked_worker_is_not_heard():
    """pm4py forks its workers: they inherit the listeners, which are not theirs."""
    heard = []

    with watch_output(lambda stream, text: heard.append(text)):
        pid = os.fork()
        if pid == 0:  # the worker
            status = 2
            try:
                sys.stdout.write('')        # goes through the stand-in of the parent
                sys.stderr.write('')
                status = 1 if heard else 0
            finally:
                os._exit(status)
        _, status = os.waitpid(pid, 0)

    assert os.WEXITSTATUS(status) == 0


# --- the operations in progress ----------------------------------------------------------------

def test_an_operation_can_be_followed_while_it_runs():
    assert progress.snapshot('job') is None

    with track('job', plan()) as followed:
        followed.start('second')
        assert progress.snapshot('job')['label'] == 'Doing the second thing'
        assert progress.snapshot('another job') is None

    assert progress.snapshot('job') is None


def test_an_operation_that_fails_is_no_longer_in_progress():
    with pytest.raises(RuntimeError):
        with track('job', plan()):
            raise RuntimeError('it failed')

    assert progress.snapshot('job') is None


def test_what_the_work_prints_moves_it():
    with track('job', discovery_steps(), LIBRARY_STEPS):
        print('Feature discovery...')
        sys.stderr.write(PM4PY_BAR)
        report = progress.snapshot('job')

    assert report['label'] == 'Replaying the log on the model'
    assert (report['done'], report['total'], report['unit']) == (506, 608, 'variants')


def test_a_run_that_ends_does_not_take_away_the_one_that_replaced_it():
    with track('job', plan()):
        with track('job', plan()) as second:
            second.start('third')
        # the inner run is over and has left; the outer one is not looked up any more
        assert progress.snapshot('job') is None
    assert progress.snapshot('job') is None


# --- a real discovery -----------------------------------------------------------------------------

@pytest.fixture
def followed_discovery(monkeypatch):
    """What a discovery reported: the steps it began, its notes, a report after each change."""
    seen = {'steps': [], 'notes': [], 'reports': []}

    def recording(name, keep):
        original = getattr(Progress, name)

        def method(self, *args, **kwargs):
            original(self, *args, **kwargs)
            if keep is not None:
                seen[keep].append(args[0])
            seen['reports'].append(self.snapshot())
        monkeypatch.setattr(Progress, name, method)

    recording('start', 'steps')
    recording('note', 'notes')
    recording('bar', None)
    return seen


@pytest.fixture
def log_with_an_attribute(tmp_path):
    rows = event_rows(cases=6)
    for position, row in enumerate(rows):
        row['amount'] = 100 + position
    return write_xes(rows, tmp_path / 'with-attribute.xes')


def test_nothing_is_in_progress_before_and_after_a_discovery(client, discovered, tiny_xes_path):
    session_id, _ = discovered(tiny_xes_path)

    response = client.get(f'/api/discover/{session_id}/progress')

    assert response.get_json() == {'in_progress': False, 'message': ''}
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/api/discover/424242/progress').get_json()['in_progress'] is False


def test_a_discovery_goes_through_every_step_of_its_plan(client, discovered, log_with_an_attribute, followed_discovery):
    """Also the alarm for a new version of prosit-pm that names its steps differently."""
    discovered(log_with_an_attribute)

    assert followed_discovery['steps'] == [step.key for step in discovery_steps()]
    assert followed_discovery['notes'] == []


def test_an_incremental_discovery_goes_through_every_step_of_its_plan(client, discovered, log_with_an_attribute,
                                                                    followed_discovery):
    discovered(log_with_an_attribute, '?max_depth_tree=1&incremental_discovery=1&grace_period=1')

    assert followed_discovery['steps'] == [step.key for step in discovery_steps(incremental=True)]
    assert followed_discovery['notes'] == []


def test_a_discovery_with_an_imported_model_goes_through_every_step(client, discovered, small_xes_path,
                                                                   small_pnml_path, followed_discovery):
    discovered(small_xes_path, pnml_path=small_pnml_path)

    reports = followed_discovery['reports']
    assert 'Reading the Petri net' in [report['label'] for report in reports]
    # purchasing.xes has no data attribute: that step is skipped, the others all run
    expected = [step.key for step in discovery_steps(importing_model=True) if step.key != 'attributes']
    assert followed_discovery['steps'] == expected
    # the steps that take long say how far they are
    counted = {(report['label'], report['unit']) for report in reports if 'total' in report}
    assert ('Reading the event log', 'traces') in counted
    assert ('Measuring the fitness of the model', 'variants') in counted
    assert ('Measuring the precision of the model', 'variants') in counted
    assert ('Replaying the log on the model', 'variants') in counted
    assert ('Fitting the models', 'models') in counted
    percents = [report['percent'] for report in reports]
    assert percents == sorted(percents) and percents[0] < 10 and 90 < percents[-1] < 100


def test_a_discovery_that_fails_is_no_longer_in_progress(client, upload, tiny_xes_path, monkeypatch):
    def fail(self, **options):
        raise DiscoveryError('nothing can be learnt from this log')

    monkeypatch.setattr(ProSiTIntegration, 'discover_parameters', fail)
    out = sys.stdout
    session_id = upload(tiny_xes_path).get_json()['session_id']

    response = client.post(f'/api/discover/{session_id}')

    assert response.status_code == 422
    assert client.get(f'/api/discover/{session_id}/progress').get_json()['in_progress'] is False
    assert sys.stdout is out


def test_the_progress_can_be_asked_while_the_discovery_runs(app, client, upload, small_xes_path):
    """The page asks from another connection: the server must answer it meanwhile."""
    session_id = upload(small_xes_path).get_json()['session_id']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    outcome, reports = {}, []

    with live_prosit(app) as port:
        base = f'http://{HOST}:{port}/api/discover/{session_id}'

        def discover():
            try:
                with opener.open(urllib.request.Request(base, method='POST'), timeout=300) as response:
                    outcome['status'] = response.status
                    outcome['body'] = json.load(response)
            except Exception as error:  # reported by the assertion below
                outcome['error'] = error

        worker = threading.Thread(target=discover)
        worker.start()
        while worker.is_alive():
            with opener.open(f'{base}/progress', timeout=60) as response:
                report = json.load(response)
            if report['in_progress']:
                reports.append(report)
            time.sleep(0.05)
        worker.join()
        with opener.open(f'{base}/progress', timeout=60) as response:
            afterwards = json.load(response)

    assert outcome.get('status') == 200, outcome
    assert outcome['body']['success'] is True
    assert afterwards == {'in_progress': False, 'message': ''}
    assert len({report['step'] for report in reports}) >= 4, reports
    assert all(report['steps'] == len(discovery_steps()) for report in reports)
    percents = [report['percent'] for report in reports]
    assert percents == sorted(percents) and percents[-1] > 50
    assert any('total' in report for report in reports)
