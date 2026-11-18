"""How far a long operation has got, for the page to show while it waits.

A discovery takes from a few seconds to many minutes. While it runs, the page
asks where it is and shows a bar with the step in progress. What is known about
"where it is" comes from two sources:

* the steps this tool runs itself, announced with :meth:`Progress.start`;
* what the libraries doing the work say while they work. prosit-pm prints the
  name of every step it begins, and both prosit-pm and pm4py draw a progress
  bar (tqdm) for whatever takes long. :func:`watch_output` hands that output,
  as written by the thread doing the work, to a :class:`LibraryOutput`, which
  turns it into steps and fractions of a step.

Nothing here knows about the discovery: a plan is a list of :class:`Step`, and
``track(key, steps)`` makes its progress readable under ``key`` for as long as
the work lasts.
"""

import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bar:
    """A progress bar that a step is known to draw."""

    share: float = 1.0  # the part of its step that it covers
    unit: str = ''      # what it counts, for the caption ("34 of 98 variants")


@dataclass(frozen=True)
class Step:
    """One step of a plan."""

    key: str
    label: str                 # shown while the step runs
    weight: float = 1.0        # how long it usually takes, relative to the other steps
    bars: tuple = (Bar(),)     # the progress bars it draws, in order


class Progress:
    """Where a planned sequence of steps has got.

    The thread doing the work calls :meth:`start`, :meth:`bar` and
    :meth:`note`; any thread may call :meth:`snapshot`. No lock is involved:
    the state is one tuple, replaced as a whole. This matters because pm4py
    starts its worker processes by forking, and a lock that another thread
    happens to hold at that moment stays locked for ever in the child.
    """

    def __init__(self, steps, clock=time.monotonic):
        self._steps = tuple(steps)
        if not self._steps:
            raise ValueError('a plan needs at least one step')
        self._positions = {step.key: position for position, step in enumerate(self._steps)}
        self._total = sum(step.weight for step in self._steps) or 1.0
        self._clock = clock
        self._started = clock()
        # (position, fraction of the step, bars seen in the step, description
        # and percentage of the bar being drawn, (done, total, unit), note)
        self._state = (0, 0.0, 0, None, 0, None, '')

    def start(self, key):
        """Step ``key`` begins, so every step before it is over.

        Steps only move forward: a key that is not in the plan, or that lies
        behind the step in progress, changes nothing.
        """
        position = self._positions.get(key)
        if position is None or position <= self._state[0]:
            return
        self._state = (position, 0.0, 0, None, 0, None, '')

    def note(self, text):
        """The work says it is doing something the plan has no step for."""
        self._state = self._state[:6] + (text,)

    def bar(self, description, percent, done=None, total=None, unit=''):
        """A progress bar drawn by the step in progress shows ``percent``.

        ``unit`` is what the bar says it counts; when it does not say, it is
        what the plan expects this bar of the step to count.
        """
        position, fraction, seen, last_description, last_percent, count, note = self._state
        step = self._steps[position]
        percent = min(max(percent, 0), 100)
        # A bar starts at zero and never goes back: anything else is a new one.
        if seen == 0 or description != last_description or percent < last_percent:
            seen += 1
        if seen <= len(step.bars):
            known = step.bars[seen - 1]
            whole = sum(bar.share for bar in step.bars) or 1.0
            before = sum(bar.share for bar in step.bars[:seen - 1])
            fraction = max(fraction, (before + known.share * percent / 100) / whole)
            count = (done, total, unit or known.unit) if total else None
        # One bar more than the step is known to draw: there is no telling how
        # much of the step it stands for, so the step stays where it is.
        self._state = (position, fraction, seen, description, percent, count, note)

    def snapshot(self):
        """What the page shows, as a JSON-ready dict."""
        position, fraction, _, _, _, count, note = self._state
        step = self._steps[position]
        before = sum(earlier.weight for earlier in self._steps[:position])
        percent = 100.0 * (before + step.weight * fraction) / self._total
        label = note or step.label
        message = label
        report = {
            'in_progress': True,
            # It is over when the answer arrives, not when the last bar is full.
            'percent': round(min(percent, 99.0), 1),
            'step': position + 1,
            'steps': len(self._steps),
            'label': label,
            'elapsed': round(self._clock() - self._started, 1),
        }
        if count is not None:
            done, total, unit = count
            report.update(done=done, total=total, unit=unit)
            message = f'{label} ({done} of {total}{" " + unit if unit else ""})'
        report['message'] = message
        return report


# --- what the libraries say while they work -----------------------------------------

# A tqdm bar: "aligning log, completed variants ::  83%|████▎ | 506/608 [00:00<00:00, 2556it/s]"
_PERCENT = re.compile(r'(\d{1,3})%\|')
_COUNT = re.compile(r'\|\s*(\d+)/(\d+)[\s\[]')
# pm4py names what its bars count: "aligning log, completed variants".
_COUNTED = re.compile(r'\bcompleted (\w+)$')
_LINE_END = re.compile(r'[\r\n]')
# An unfinished line longer than this is not the name of a step.
_LONGEST_LINE = 500


def _same_words(text):
    return ' '.join(text.lower().rstrip('. ').split())


class LibraryOutput:
    """Turns what a library writes while it works into progress.

    ``announcements`` maps a line the library prints when it begins a step to
    the key of that step in the plan. A line ending in "..." that is not among
    them is still shown, as it is, until the next step begins: a newer version
    of the library may have steps this tool has not heard of.
    """

    def __init__(self, progress, announcements=None):
        self._progress = progress
        self._announcements = {_same_words(line): key for line, key in (announcements or {}).items()}
        self._unfinished = {}

    def __call__(self, stream, text):
        meter = self._meter(text)
        if meter is not None:
            self._progress.bar(*meter)
            return
        *lines, unfinished = _LINE_END.split(self._unfinished.get(stream, '') + text)
        self._unfinished[stream] = unfinished[-_LONGEST_LINE:]
        for line in lines:
            self._announce(line.strip())

    @staticmethod
    def _meter(text):
        """``(description, percent, done, total, unit)`` of the progress bar in ``text``, if any."""
        found = None
        for found in _PERCENT.finditer(text):
            pass  # the last one: what the bar shows now
        if found is None:
            return None
        line_start = max(text.rfind('\r', 0, found.start()), text.rfind('\n', 0, found.start())) + 1
        description = text[line_start:found.start()].strip().rstrip(':').strip()
        count = _COUNT.search(text, found.end() - 1)
        done, total = (int(count.group(1)), int(count.group(2))) if count else (None, None)
        counted = _COUNTED.search(description)
        return description, int(found.group(1)), done, total, counted.group(1) if counted else ''

    def _announce(self, line):
        if not line:
            return
        key = self._announcements.get(_same_words(line))
        if key is not None:
            self._progress.start(key)
        elif line.endswith('...'):
            self._progress.note(line.rstrip('. '))


# --- reading the output of one thread -------------------------------------------------

_watch_lock = threading.Lock()
_listeners = {}                               # thread id -> listener(stream name, text)
_routers = {'stdout': None, 'stderr': None}   # what stands in for sys.stdout / sys.stderr


class _Router:
    """Stands in for ``sys.stdout`` or ``sys.stderr`` while someone listens.

    Everything is passed on to the real stream; what a listening thread writes
    is shown to its listener first.
    """

    def __init__(self, name, stream):
        self._name = name
        self._stream = stream
        self._process = os.getpid()

    def write(self, text):
        listener = _listeners.get(threading.get_ident())
        # A forked worker inherits this object together with the listeners of
        # its parent: they are not its own.
        if listener is not None and os.getpid() == self._process:
            try:
                listener(self._name, text)
            except Exception:  # reporting must never break the work it reports on
                logger.debug('Could not read the output of the work in progress', exc_info=True)
        if self._stream is None:  # a program without a console
            return len(text)
        return self._stream.write(text)

    def flush(self):
        if self._stream is not None:
            self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


@contextmanager
def watch_output(listener):
    """Call ``listener(stream, text)`` for what this thread writes to stdout and stderr.

    Only the calling thread is listened to: what other requests print in the
    meantime goes where it always went, and so does, after the listener has
    seen it, what this thread prints.
    """
    ident = threading.get_ident()
    with _watch_lock:
        previous = _listeners.get(ident)
        for name in _routers:
            if _routers[name] is None or getattr(sys, name) is not _routers[name]:
                _routers[name] = _Router(name, getattr(sys, name))
                setattr(sys, name, _routers[name])
        _listeners[ident] = listener
    try:
        yield
    finally:
        with _watch_lock:
            if previous is None:
                _listeners.pop(ident, None)
            else:
                _listeners[ident] = previous
            if not _listeners:
                for name, router in _routers.items():
                    # Whoever replaced the stream in the meantime keeps theirs.
                    if router is not None and getattr(sys, name) is router:
                        setattr(sys, name, router._stream)
                    _routers[name] = None


# --- the operations in progress ---------------------------------------------------------

_running = {}
_running_lock = threading.Lock()


@contextmanager
def track(key, steps, announcements=None):
    """Follow the work done inside the block; yields its :class:`Progress`.

    While the block runs, ``snapshot(key)`` tells any thread how far it has
    got. Besides the steps the caller starts itself, the output of the calling
    thread is read for the steps and the progress bars of the libraries it
    calls (see :class:`LibraryOutput`).
    """
    progress = Progress(steps)
    with _running_lock:
        _running[key] = progress
    try:
        with watch_output(LibraryOutput(progress, announcements)):
            yield progress
    finally:
        with _running_lock:
            # A later run under the same key has its own progress: leave it.
            if _running.get(key) is progress:
                del _running[key]


def snapshot(key):
    """How far the operation running under ``key`` has got; ``None`` when there is none."""
    progress = _running.get(key)
    return progress.snapshot() if progress is not None else None
