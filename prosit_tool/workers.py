"""Worker processes for the executable.

prosit-pm fits its models with joblib, on as many processes as the computer
has processors but one. joblib starts those processes with ``python -m ...``,
a command that an executable built by PyInstaller does not understand: left
to itself, an executable would fit every model in its one process.

What an executable does understand is the way the standard ``multiprocessing``
starts a process: by running the program again with arguments that
``multiprocessing.freeze_support()`` recognises (the first thing ``cli.main``
calls). pm4py's processes, the ones that align the log with the model, start
that way. ``joblib_on_worker_processes()`` gives joblib a pool of processes
started that way too, for the thread that asks and for as long as it asks.

Installed with pip, in Docker or from the source nothing changes: joblib's own
workers start there, and they are the ones prosit-pm is tried with.
"""

import concurrent.futures
import contextlib
import io
import itertools
import logging
import multiprocessing
import os
import pickle
import shutil
import sys
import tempfile
import threading
import time
import weakref

import numpy
from joblib import cpu_count, parallel_config
from joblib.parallel import FallbackToBackend, ParallelBackendBase, SequentialBackend

from . import worker_process

try:
    import cloudpickle
except ImportError:  # joblib up to 1.5 brings its own copy
    from joblib.externals import cloudpickle

logger = logging.getLogger(__name__)

# Windows cannot wait for more processes than this at once.
MOST_WORKERS_ON_WINDOWS = 61
# How long the first worker may take to answer. It takes a second or two; an
# antivirus looking at a program it has never seen can make it many more.
START_TIMEOUT = 60
# How long the processes of a pool are waited for, once told to stop.
STOP_TIMEOUT = 5
# From this many bytes an array is not sent to the worker that needs it but
# written to a file that the workers read in place: the size from which
# joblib does the same for its own workers.
SHARED_FROM = 1_000_000
# The folder of those files, in the temporary directory of the system, begins
# with this. A program that is killed leaves its folder behind: one that
# nothing has been written to for this many seconds is removed by the next
# discovery that needs a folder.
FOLDER_PREFIX = 'prosit-tool-'
FORGOTTEN_AFTER = 24 * 60 * 60

_lock = threading.Lock()
# The pools in use, to stop them when the program is closed; from then on
# none is started.
_pools = set()
_closing = False
# Folders of shared arrays that could not be removed when their pool stopped.
_leftovers = []

_trying = threading.Lock()
# Why worker processes cannot be started on this computer; '' when they can,
# None until it has been tried (once for every run of the program).
_problem = None


def in_an_executable():
    return bool(getattr(sys, 'frozen', False))


# --- what goes to the workers ----------------------------------------------------------------

class SharedArrays:
    """The large arrays of the jobs, each written once to a file.

    prosit-pm gives every job that fits a tree the same table, with the rows
    of the job: it counts on joblib, which does not send a large array to each
    of its workers but writes it to a file they all read in place. Sent with
    every job instead, the table would be copied hundreds of times.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._folder = None
        self._number = itertools.count()
        self._files = {}  # id of an array -> (the array, held weakly; its file)
        self._cleared = False

    def file_of(self, array):
        """The file with ``array``, written now if it is not there; None if it cannot be written."""
        with self._lock:
            if self._cleared:
                # A job that was leaving while its pool was stopped: no worker
                # will read it, nothing is written for it.
                return None
            known = self._files.get(id(array))
            if known is not None and known[0]() is array:
                return known[1]
            path = None
            try:
                if self._folder is None:
                    _remove_forgotten_folders()
                    self._folder = tempfile.mkdtemp(prefix=FOLDER_PREFIX)
                path = os.path.join(self._folder, f'{next(self._number)}.npy')
                numpy.save(path, array, allow_pickle=False)
            except (OSError, ValueError) as exc:
                # No room, most likely: the array travels with every job that
                # needs it, and writing it is not tried again.
                logger.warning('An array of %d bytes could not be shared with the workers: %s', array.nbytes, exc)
                if path is not None:
                    with contextlib.suppress(OSError):
                        os.remove(path)
                path = None
            self._files[id(array)] = (weakref.ref(array), path)
            return path

    def clear(self):
        """Remove the files, for good: the workers that read them have been stopped."""
        with self._lock:
            folder, self._folder, self._files, self._cleared = self._folder, None, {}, True
        if folder is not None:
            with _lock:
                _leftovers.append(folder)
        _remove_leftovers()


def _remove_forgotten_folders():
    """Remove the folders that programs killed in the middle of a discovery left behind."""
    now = time.time()
    with contextlib.suppress(OSError):
        with os.scandir(tempfile.gettempdir()) as entries:
            for entry in entries:
                with contextlib.suppress(OSError):
                    if (entry.name.startswith(FOLDER_PREFIX) and entry.is_dir(follow_symlinks=False)
                            and now - entry.stat(follow_symlinks=False).st_mtime > FORGOTTEN_AFTER):
                        shutil.rmtree(entry.path, ignore_errors=True)


def _remove_leftovers():
    with _lock:
        folders, _leftovers[:] = list(_leftovers), []
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)
        if os.path.exists(folder):
            # Windows does not remove a file while a process that is ending
            # still has it open: it is tried again later.
            with _lock:
                _leftovers.append(folder)


class _Pickler(cloudpickle.CloudPickler):
    """Pickles as joblib's own workers expect (a function may be defined where
    it is used), leaving the large arrays to ``SharedArrays``."""

    def __init__(self, file, arrays):
        super().__init__(file)
        self._arrays = arrays

    def reducer_override(self, obj):
        if type(obj) is numpy.ndarray and obj.nbytes >= SHARED_FROM and not obj.dtype.hasobject:
            path = self._arrays.file_of(obj)
            if path is not None:
                return worker_process.shared_array, (path,)
        return super().reducer_override(obj)


class Sent:
    """A job on its way to a worker.

    It is pickled only at the moment it leaves: the jobs that wait their turn,
    a couple for every worker, stay as they are.
    """

    def __init__(self, job, arrays):
        self.job = job
        self.arrays = arrays

    def __reduce__(self):
        with io.BytesIO() as pickled:
            _Pickler(pickled, self.arrays).dump(self.job)
            return pickle.loads, (pickled.getvalue(),)


# --- the processes ---------------------------------------------------------------------------

def _start(size):
    """A pool of ``size`` processes; each is started when a job needs it."""
    return concurrent.futures.ProcessPoolExecutor(
        max_workers=size,
        # On every system, also where a faster way exists (Linux): what is
        # tried on one system is then what runs on the others.
        mp_context=multiprocessing.get_context('spawn'),
        initializer=worker_process.settle_in,
        initargs=(max(cpu_count() // size, 1),),
    )


def _stop(executor):
    """Stop the processes of a pool now, whatever they are doing."""
    # Up to Python 3.13 a pool has no public way to say which its processes are.
    processes = list((getattr(executor, '_processes', None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        with contextlib.suppress(Exception):
            process.terminate()
    deadline = time.monotonic() + STOP_TIMEOUT
    for process in processes:
        with contextlib.suppress(Exception):
            process.join(timeout=max(deadline - time.monotonic(), 0))


class Pool:
    """Worker processes, started with the first job and kept until ``stop``."""

    def __init__(self):
        self._lock = threading.Lock()
        self._executor = None
        self._size = 0
        # The large arrays of the jobs of the processes in use.
        self.arrays = SharedArrays()

    def executor(self, size):
        """The pool of ``size`` processes: the one in use, if it is that large."""
        with self._lock:
            if self._executor is None or self._size != size:
                self._stop()
                with _lock:
                    if _closing:
                        raise RuntimeError('the program is being closed')
                    _pools.add(self)
                self._executor, self._size, self.arrays = _start(size), size, SharedArrays()
            return self._executor

    def stop(self):
        with self._lock:
            self._stop()

    def _stop(self):
        executor, self._executor = self._executor, None
        with _lock:
            _pools.discard(self)
        if executor is not None:
            _stop(executor)
        self.arrays.clear()


def stop_all():
    """Stop every pool in use and start no other: the program is being closed.

    Without this the program would not close until the jobs already given to
    the workers are done: Python waits for them when it ends.
    """
    global _closing
    with _lock:
        _closing = True
        pools = list(_pools)
    for pool in pools:
        pool.stop()
    _remove_leftovers()


def _try_a_worker():
    """Start a worker process and give it a job; say what goes wrong, if anything does."""
    pool = Pool()
    try:
        pool.executor(1).submit(worker_process.ready).result(timeout=START_TIMEOUT)
    except concurrent.futures.TimeoutError:
        return f'no answer from a worker process after {START_TIMEOUT} seconds'
    except Exception as exc:
        return f'{type(exc).__name__}: {exc}'.strip().rstrip(':')
    finally:
        pool.stop()
    return ''


def problem(check=True):
    """Why worker processes cannot be started here; '' if they can.

    It is tried the first time someone asks, and remembered. With
    ``check=False`` the answer is what is known so far ('' if never tried).
    """
    global _problem
    if _problem is None and check:
        with _trying:
            if _problem is None:
                _problem = _try_a_worker()
                if _problem:
                    logger.warning('Worker processes cannot be started, the models are fitted '
                                   'by one process: %s', _problem)
                else:
                    logger.info('Worker processes can be started')
    return _problem or ''


# --- joblib ----------------------------------------------------------------------------------

class WorkerProcesses(ParallelBackendBase):
    """What joblib needs to know to run its jobs on a ``Pool``."""

    supports_retrieve_callback = True

    def __init__(self, pool, **settings):
        super().__init__(**settings)
        self._pool = pool
        self._executor = None
        self._size = 0

    def effective_n_jobs(self, n_jobs):
        if n_jobs == 0:
            raise ValueError('n_jobs == 0 in Parallel has no meaning')
        if n_jobs is None:
            return 1
        if n_jobs < 0:
            n_jobs = max(cpu_count() + 1 + n_jobs, 1)
        if sys.platform == 'win32':
            n_jobs = min(n_jobs, MOST_WORKERS_ON_WINDOWS)
        # A daemonic process may not have children.
        if n_jobs > 1 and (multiprocessing.current_process().daemon or problem()):
            return 1
        return n_jobs

    def configure(self, n_jobs=1, parallel=None, **settings):
        n_jobs = self.effective_n_jobs(n_jobs)
        if n_jobs == 1:
            raise FallbackToBackend(SequentialBackend(nesting_level=self.nesting_level))
        self.parallel = parallel
        self._executor, self._size = self._pool.executor(n_jobs), n_jobs
        return n_jobs

    def submit(self, func, callback=None):
        future = self._executor.submit(worker_process.run, Sent(func, self._pool.arrays))
        if callback is not None:
            future.add_done_callback(callback)
        return future

    apply_async = submit  # its name up to joblib 1.4

    def retrieve_result_callback(self, future):
        return pickle.loads(future.result())

    def terminate(self):
        # The processes stay: the next call of the same discovery uses them.
        self._executor = None

    def abort_everything(self, ensure_ready=True):
        self._pool.stop()
        if ensure_ready:
            self._executor = self._pool.executor(self._size)


@contextlib.contextmanager
def joblib_on_worker_processes(needed=None):
    """Inside, the joblib of the calling thread runs its jobs on processes that
    an executable can start. Outside an executable it changes nothing, unless
    ``needed`` says otherwise."""
    if needed is None:
        needed = in_an_executable()
    if not needed:
        yield
        return
    pool = Pool()
    try:
        with parallel_config(backend=WorkerProcesses(pool)):
            yield
    finally:
        pool.stop()
