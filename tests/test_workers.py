"""The processes that fit the models when the tool is an executable (``prosit_tool.workers``).

An executable cannot start joblib's own workers. It gets processes started the
way the standard ``multiprocessing`` starts them with its "spawn" method, which
works from the source too: that is how these tests run them.
"""

import concurrent.futures
import multiprocessing
import os
import pickle
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import numpy
import pandas
import pytest
from joblib import Parallel, cpu_count, delayed, effective_n_jobs
from joblib.parallel import get_active_backend

from prosit_tool import cli, worker_process, workers

REPO = Path(__file__).resolve().parents[1]
HOST = '127.0.0.1'

posix_only = pytest.mark.skipif(os.name != 'posix', reason='looks at processes the way POSIX lets one')


@pytest.fixture(autouse=True)
def as_when_the_program_starts(monkeypatch):
    """Nothing is known about worker processes and none is in use; none is left behind."""
    monkeypatch.setattr(workers, '_problem', None)
    monkeypatch.setattr(workers, '_closing', False)
    yield
    workers.stop_all()


class Seen:
    """The pools started during a test, and the processes they had when they were stopped."""

    def __init__(self):
        self.pools = []
        self.processes = []


@pytest.fixture
def seen(monkeypatch):
    assert workers.problem() == ''                       # tried before, with a pool that is not among these
    seen = Seen()
    start, stop = workers._start, workers._stop

    def started(size):
        seen.pools.append(start(size))
        return seen.pools[-1]

    def stopped(executor):
        seen.processes.extend((executor._processes or {}).values())
        stop(executor)

    monkeypatch.setattr(workers, '_start', started)
    monkeypatch.setattr(workers, '_stop', stopped)
    return seen


def cannot_start(monkeypatch, reason='no more processes'):
    def refuse(size):
        raise OSError(reason)

    monkeypatch.setattr(workers, '_start', refuse)


def exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_until(condition, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def ended(processes):
    """True if there are processes and all of them have ended.

    Asked the instant a process ends, ``is_alive`` may still say yes: the pool
    waits for its processes too, and only one of the two that wait is told.
    """
    return bool(processes) and wait_until(lambda: not any(process.is_alive() for process in processes), 10)


# --- the jobs -----------------------------------------------------------------------------------

def test_jobs_run_in_other_processes_and_are_handed_back_as_they_finish():
    with workers.joblib_on_worker_processes(needed=True):
        # the way prosit-pm asks for them: in the order in which they are ready
        pids = set(Parallel(n_jobs=2, return_as='generator_unordered')(delayed(os.getpid)() for _ in range(6)))

    assert pids and os.getpid() not in pids
    assert len(pids) <= 2


def test_a_job_may_be_a_function_written_where_it_is_used():
    """As with joblib's own workers: the standard pickle refuses such a job, and such a result."""
    offset = 10

    with workers.joblib_on_worker_processes(needed=True):
        sums = Parallel(n_jobs=2)(delayed(lambda value: value + offset)(value) for value in range(3))
        double, = Parallel(n_jobs=2)([delayed(lambda: lambda value: value * 2)()])

    assert sums == [10, 11, 12]
    assert double(21) == 42


def test_what_goes_wrong_in_a_job_is_raised_where_the_jobs_were_given():
    def fit(name):
        raise KeyError(f'no data for {name}')

    with workers.joblib_on_worker_processes(needed=True):
        with pytest.raises(KeyError, match='no data for'):
            Parallel(n_jobs=2)(delayed(fit)(name) for name in 'ab')
        # and the next call finds processes to work with
        assert Parallel(n_jobs=2)(delayed(abs)(-1) for _ in range(2)) == [1, 1]


def test_a_job_that_cannot_be_sent_is_an_error_not_a_wait():
    """A job is pickled when it leaves for a worker, not when it is given: it is there that it can fail."""
    lock = threading.Lock()

    with workers.joblib_on_worker_processes(needed=True):
        with pytest.raises(TypeError, match='pickle'):
            Parallel(n_jobs=2)([delayed(lambda: lock.locked())()])


def test_jobs_that_wait_their_turn_are_not_copied(monkeypatch):
    """They are a couple for every worker and their data can be large: a job is pickled when it leaves."""
    pickled, dump = [], workers._Pickler.dump
    monkeypatch.setattr(workers._Pickler, 'dump', lambda self, job: pickled.append(job) or dump(self, job))

    sent = workers.Sent(abs, workers.SharedArrays())     # given to the pool
    assert pickled == []

    assert pickle.loads(pickle.dumps(sent)) is abs       # what the pool does when its turn comes
    assert pickled == [abs]


# --- large arrays ---------------------------------------------------------------------------------

@pytest.fixture
def shared(monkeypatch):
    """The file of every large array met in a job, in the order in which they are met."""
    files = []
    file_of = workers.SharedArrays.file_of

    def recorded(self, array):
        files.append(file_of(self, array))
        return files[-1]

    monkeypatch.setattr(workers.SharedArrays, 'file_of', recorded)
    return files


def look(table, row):
    """What a worker finds: the kind of array, whether it may write to it, a value, where it comes from."""
    return type(table).__name__, bool(table.flags.writeable), float(table[row, 0]), getattr(table, 'filename', None)


def test_a_large_array_is_written_once_and_read_in_place_by_every_job(shared):
    """prosit-pm gives the same table to every job that fits a tree, as joblib lets it."""
    table = numpy.arange(300_000, dtype='float64').reshape(-1, 3)      # 2.4 MB

    with workers.joblib_on_worker_processes(needed=True):
        found = Parallel(n_jobs=2)(delayed(look)(table, row) for row in range(4))
        assert len(shared) == 4 and len(set(shared)) == 1               # asked for by every job: one file
        assert os.path.isfile(shared[0])

    assert [what[:3] for what in found] == [('memmap', False, 3.0 * row) for row in range(4)]
    assert {str(what[3]) for what in found} == {shared[0]}
    # the file lasts as long as the workers that read it
    assert not os.path.exists(os.path.dirname(shared[0]))


def test_the_columns_of_a_table_are_shared_too(shared):
    frame = pandas.DataFrame({'a': numpy.arange(200_000, dtype='float64'), 'b': 1.5})

    with workers.joblib_on_worker_processes(needed=True):
        sums = Parallel(n_jobs=2)(delayed(lambda frame, column: float(frame[column].sum()))(frame, column)
                                  for column in 'ab')

    assert sums == [float(frame['a'].sum()), float(frame['b'].sum())]
    assert shared and all(shared)


def test_what_is_small_or_not_made_of_numbers_travels_with_its_job(shared):
    small = numpy.arange(30, dtype='float64').reshape(-1, 3)
    names = numpy.array(['a name'] * 300_000, dtype=object).reshape(-1, 3)

    with workers.joblib_on_worker_processes(needed=True):
        found = Parallel(n_jobs=2)([delayed(look)(small, 1), delayed(lambda names: names[1, 0])(names)])

    assert found == [('ndarray', True, 3.0, None), 'a name']
    assert shared == []


def test_a_folder_left_by_a_program_that_was_killed_is_removed_by_a_later_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(workers.tempfile, 'tempdir', str(tmp_path))
    forgotten, recent, of_another_program = (tmp_path / name for name in
                                             ('prosit-tool-killed', 'prosit-tool-at-work', 'something-else'))
    for folder in (forgotten, recent, of_another_program):
        folder.mkdir()
        (folder / '0.npy').write_bytes(b'what was left')
    long_ago = time.time() - workers.FORGOTTEN_AFTER - 60
    os.utime(forgotten, (long_ago, long_ago))
    os.utime(of_another_program, (long_ago, long_ago))

    arrays = workers.SharedArrays()
    written = arrays.file_of(numpy.zeros(3))

    assert not forgotten.exists()
    assert recent.exists() and of_another_program.exists()
    assert Path(written).parent.parent == tmp_path and Path(written).parent.name.startswith('prosit-tool-')
    arrays.clear()
    assert not Path(written).parent.exists()


def test_a_job_that_leaves_after_its_pool_was_stopped_writes_nothing(tmp_path, monkeypatch):
    """When the program is closed in the middle of a discovery, a job may be on its way."""
    monkeypatch.setattr(workers.tempfile, 'tempdir', str(tmp_path))
    arrays = workers.SharedArrays()
    table = numpy.zeros(200_000)
    assert arrays.file_of(table)

    arrays.clear()

    assert arrays.file_of(table) is None
    assert list(tmp_path.iterdir()) == []


def test_where_a_file_cannot_be_read_in_place_a_worker_reads_all_of_it(tmp_path, monkeypatch):
    path = tmp_path / 'table.npy'
    numpy.save(path, numpy.arange(6.0))
    load = numpy.load

    def never_in_place(file, mmap_mode=None, **options):
        if mmap_mode:
            raise OSError(19, 'No such device')
        return load(file, **options)

    monkeypatch.setattr(numpy, 'load', never_in_place)

    table = worker_process.shared_array(str(path))

    assert table.tolist() == [0, 1, 2, 3, 4, 5]
    assert not table.flags.writeable                     # as when it is read in place


def test_an_array_that_cannot_be_written_to_a_file_travels_with_its_job(shared, monkeypatch):
    def no_room(path, array, **options):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(workers.numpy, 'save', no_room)
    table = numpy.arange(300_000, dtype='float64').reshape(-1, 3)

    with workers.joblib_on_worker_processes(needed=True):
        found = Parallel(n_jobs=2)(delayed(look)(table, row) for row in range(2))

    assert found == [('ndarray', True, 0.0, None), ('ndarray', True, 3.0, None)]
    assert shared == [None, None]


def test_one_pool_serves_every_call_and_ends_with_the_discovery(seen):
    with workers.joblib_on_worker_processes(needed=True):
        first = Parallel(n_jobs=2)(delayed(os.getpid)() for _ in range(4))
        second = Parallel(n_jobs=2)(delayed(os.getpid)() for _ in range(4))
        assert len(seen.pools) == 1
        assert seen.processes == []                      # still at work

    assert set(first) | set(second) <= {process.pid for process in seen.processes}
    assert ended(seen.processes)


def test_a_job_that_fails_stops_the_others_at_once(seen):
    started = time.monotonic()

    with workers.joblib_on_worker_processes(needed=True):
        with pytest.raises(ZeroDivisionError):
            Parallel(n_jobs=2)([delayed(time.sleep)(600), delayed(lambda: 1 / 0)()])
        # now, not when the discovery ends
        assert ended(seen.processes)

    assert time.monotonic() - started < 300


# --- the processes ------------------------------------------------------------------------------

def test_a_worker_gets_its_share_of_the_processors(monkeypatch):
    def threads():
        return os.environ['OMP_NUM_THREADS'], os.environ['OPENBLAS_NUM_THREADS']

    for name in worker_process.THREAD_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    share = str(max(cpu_count() // 2, 1))

    with workers.joblib_on_worker_processes(needed=True):
        assert set(Parallel(n_jobs=2)(delayed(threads)() for _ in range(4))) == {(share, share)}

    # what the user has chosen is kept
    monkeypatch.setenv('OMP_NUM_THREADS', '3')
    with workers.joblib_on_worker_processes(needed=True):
        assert set(Parallel(n_jobs=2)(delayed(threads)() for _ in range(4))) == {('3', share)}


def test_nothing_heavy_is_loaded_before_a_worker_settles_in():
    """The numerical libraries read how many threads they may use at the moment they are
    loaded: neither the launcher, which a worker of the executable runs first, nor the
    module with its first job may load them."""
    loaded = subprocess.run(
        [sys.executable, '-c',
         'import sys, prosit_tool.cli, prosit_tool.worker_process\n'
         'print([name for name in ("numpy", "scipy", "pandas", "sklearn", "joblib") if name in sys.modules])'],
        cwd=REPO, capture_output=True, text=True, check=True)

    assert loaded.stdout.strip() == '[]'


@posix_only
def test_ctrl_c_is_for_the_program_to_deal_with():
    """A terminal sends it to every process: a worker goes on until the program stops it."""
    pool = workers.Pool()
    try:
        executor = pool.executor(1)
        worker = executor.submit(worker_process.ready).result(timeout=120)

        os.kill(worker, signal.SIGINT)
        time.sleep(0.5)

        assert executor.submit(worker_process.ready).result(timeout=120) == worker
    finally:
        pool.stop()


@posix_only
def test_a_worker_does_not_outlive_the_program(tmp_path):
    """Killed, the program stops nobody: a worker notices by itself."""
    program = tmp_path / 'program.py'
    program.write_text(textwrap.dedent('''
        import time

        from prosit_tool import worker_process, workers

        if __name__ == '__main__':
            pool = workers.Pool()
            print(pool.executor(1).submit(worker_process.ready).result(timeout=120), flush=True)
            time.sleep(600)
    '''))
    process = subprocess.Popen([sys.executable, str(program)], cwd=tmp_path, stdout=subprocess.PIPE, text=True,
                               env={**os.environ, 'PYTHONPATH': str(REPO)})
    worker = None
    try:
        worker = int(process.stdout.readline())
        assert exists(worker)

        process.kill()
        process.wait(timeout=30)

        assert wait_until(lambda: not exists(worker), 30), 'the worker is still there'
    finally:
        process.kill()
        process.wait(timeout=30)
        process.stdout.close()
        if worker is not None and exists(worker):
            os.kill(worker, signal.SIGKILL)


# --- when they cannot be started ----------------------------------------------------------------

def test_whether_they_start_is_tried_once(monkeypatch):
    tries = []
    try_a_worker = workers._try_a_worker
    monkeypatch.setattr(workers, '_try_a_worker', lambda: tries.append(1) or try_a_worker())

    assert workers.problem(check=False) == '' and tries == []
    assert workers.problem() == ''
    assert workers.problem() == ''
    assert tries == [1]


def test_without_worker_processes_the_jobs_run_here_one_after_the_other(monkeypatch):
    cannot_start(monkeypatch)
    monkeypatch.setattr(workers, 'cpu_count', lambda: 4)

    with workers.joblib_on_worker_processes(needed=True):
        assert effective_n_jobs(-2) == 1                 # what prosit-pm asks before it orders its jobs
        pids = list(Parallel(n_jobs=-2, return_as='generator_unordered')(delayed(os.getpid)() for _ in range(3)))

    assert pids == [os.getpid()] * 3
    assert workers.problem(check=False) == 'OSError: no more processes'


def test_a_worker_that_dies_as_it_starts_is_a_reason(monkeypatch):
    monkeypatch.setattr(workers, '_start', lambda size: concurrent.futures.ProcessPoolExecutor(
        max_workers=size, mp_context=multiprocessing.get_context('spawn'), initializer=os._exit, initargs=(3,)))

    assert workers.problem().startswith('BrokenProcessPool')


def test_a_worker_that_never_answers_is_a_reason(monkeypatch):
    class Silent:
        def submit(self, *job):
            return concurrent.futures.Future()

        def shutdown(self, **options):
            pass

    monkeypatch.setattr(workers, '_start', lambda size: Silent())
    monkeypatch.setattr(workers, 'START_TIMEOUT', 0.05)

    assert workers.problem() == 'no answer from a worker process after 0.05 seconds'


# --- only where they are needed, only for who asks -------------------------------------------------

def test_outside_an_executable_joblib_is_left_alone():
    usual = type(get_active_backend()[0])

    with workers.joblib_on_worker_processes():
        assert type(get_active_backend()[0]) is usual

    assert usual is not workers.WorkerProcesses
    assert workers.in_an_executable() is False           # these tests run from the source


def test_in_an_executable_joblib_gets_the_pool_in_the_thread_that_asks(monkeypatch):
    monkeypatch.setattr(workers, 'in_an_executable', lambda: True)
    elsewhere = []

    with workers.joblib_on_worker_processes():
        assert isinstance(get_active_backend()[0], workers.WorkerProcesses)
        thread = threading.Thread(target=lambda: elsewhere.append(get_active_backend()[0]))
        thread.start()
        thread.join()

    assert not isinstance(elsewhere[0], workers.WorkerProcesses)
    assert not isinstance(get_active_backend()[0], workers.WorkerProcesses)


# --- a discovery -----------------------------------------------------------------------------------

def test_in_an_executable_a_discovery_fits_its_models_on_worker_processes(discovered, tiny_xes_path, monkeypatch, seen):
    monkeypatch.setattr(workers, 'in_an_executable', lambda: True)
    monkeypatch.setattr(workers, 'cpu_count', lambda: 4)
    sent, dump = [], workers._Pickler.dump
    monkeypatch.setattr(workers._Pickler, 'dump', lambda self, job: sent.append(job) or dump(self, job))

    _, body = discovered(tiny_xes_path, '?max_depth_tree=1')

    assert body['parameters']['transition_params']['transition_weights']
    assert sent, 'no job was given to a worker process'
    assert not [warning for warning in body['warnings'] if 'one process' in warning]
    # none of them is left when the discovery has answered
    assert ended(seen.processes)


def test_a_discovery_goes_on_with_one_process_and_says_so(discovered, tiny_xes_path, monkeypatch):
    monkeypatch.setattr(workers, 'in_an_executable', lambda: True)
    monkeypatch.setattr(workers, 'cpu_count', lambda: 4)
    cannot_start(monkeypatch, 'the antivirus said no')

    _, body = discovered(tiny_xes_path, '?max_depth_tree=1')

    assert body['parameters']['transition_params']['transition_weights']
    assert [warning for warning in body['warnings'] if 'one process' in warning] == [
        'The models were fitted by one process, which takes longer: the program could not '
        'start its worker processes (OSError: the antivirus said no).'
    ]


def test_installed_or_from_the_source_a_discovery_starts_none_of_them(discovered, tiny_xes_path, seen):
    _, body = discovered(tiny_xes_path, '?max_depth_tree=1')

    assert seen.pools == []
    assert not [warning for warning in body['warnings'] if 'one process' in warning]


# --- closing the program ---------------------------------------------------------------------------

def test_closing_the_program_stops_the_workers_whatever_they_are_doing(seen):
    pool = workers.Pool()
    executor = pool.executor(1)
    executor.submit(worker_process.ready).result(timeout=120)
    long_job = executor.submit(time.sleep, 600)

    workers.stop_all()

    with pytest.raises((concurrent.futures.BrokenExecutor, concurrent.futures.CancelledError)):
        long_job.result(timeout=120)
    assert ended(seen.processes)
    # and no discovery still at work starts others
    with pytest.raises(RuntimeError, match='being closed'):
        pool.executor(1)


def test_the_launcher_stops_them_after_the_server(tmp_path, monkeypatch):
    steps = []

    class Server:
        def run(self):
            raise KeyboardInterrupt                      # Ctrl+C

        def close(self):
            steps.append('server closed')

    monkeypatch.setattr('waitress.create_server', lambda application, **options: Server())
    monkeypatch.setattr(workers, 'stop_all', lambda: steps.append('workers stopped'))
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        port = probe.getsockname()[1]

    assert cli.main(['--no-browser', '--port', str(port), '--data-dir', str(tmp_path / 'data')]) == 0
    assert steps == ['server closed', 'workers stopped']


def test_the_program_can_be_asked_whether_it_starts_them(capsys, monkeypatch):
    """What the test of a built executable asks first (packaging/smoke_test.py)."""
    assert cli.main(['--check-workers']) == 0
    assert 'Worker processes can be started' in capsys.readouterr().out

    monkeypatch.setattr(workers, '_problem', None)
    cannot_start(monkeypatch)
    assert cli.main(['--check-workers']) == 1
    assert 'Worker processes cannot be started: OSError: no more processes' in capsys.readouterr().out

    # a question for who builds the program, not for who uses it
    assert 'check-workers' not in cli.build_parser().format_help()
