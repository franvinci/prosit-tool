"""What a worker process of ``workers`` runs.

Importing this module loads nothing heavy, on purpose: a worker decides how
many threads the numerical libraries may use before any of them is loaded,
which is the only moment they listen.
"""

import multiprocessing
import os
import signal
import threading

# What the numerical libraries read, once, when they are loaded.
THREAD_SETTINGS = (
    'OMP_NUM_THREADS',
    'OPENBLAS_NUM_THREADS',
    'MKL_NUM_THREADS',
    'BLIS_NUM_THREADS',
    'VECLIB_MAXIMUM_THREADS',
    'NUMEXPR_NUM_THREADS',
)


def settle_in(threads):
    """Run by a worker before its first job.

    ``threads`` is the worker's share of the processors: with one process per
    processor, libraries that each start a thread per processor would only get
    in one another's way. A value already set by the user is left alone.
    """
    for name in THREAD_SETTINGS:
        os.environ.setdefault(name, str(threads))
    # Ctrl+C reaches every process of the terminal: the program decides what
    # its workers do about it, they do not each print a traceback.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    parent = multiprocessing.parent_process()
    if parent is not None:
        threading.Thread(target=_leave_with, args=(parent,), name='leave-with-the-program', daemon=True).start()


def _leave_with(parent):
    """End when the program ends, however it ends: a worker waiting for a job
    would otherwise wait for ever."""
    parent.join()
    os._exit(1)


def ready():
    """The job that tells whether worker processes can be started at all."""
    return os.getpid()


def dumps(value):
    """Pickle, as joblib's own workers do, also what the standard pickle cannot:
    a function defined where it is used."""
    try:
        import cloudpickle
    except ImportError:  # joblib up to 1.5 brings its own copy
        from joblib.externals import cloudpickle
    return cloudpickle.dumps(value)


def shared_array(path):
    """An array that the program wrote to a file for its workers (``workers.SharedArrays``):
    read in place, so that the workers that need it hold one copy between them. It
    cannot be written to, like the arrays that joblib shares with its own workers."""
    import numpy

    try:
        return numpy.load(path, mmap_mode='r')
    except (OSError, ValueError):
        # A folder of temporary files where files cannot be read in place: a copy then.
        array = numpy.load(path)
        array.flags.writeable = False
        return array


def run(job):
    """Run a job and return what it returns, pickled by ``dumps``."""
    return dumps(job())
