"""Helpers shared across multiple API blueprints."""

import json
import logging
import os
import re
import sys
import tempfile
import threading
import time

import pm4py
from flask import current_app
from pm4py.objects.log.importer.xes import importer as xes_importer

from ..prosit_integration import ProSiTIntegration, describe_exception

logger = logging.getLogger(__name__)

# Name given to the resource of events that carry none. prosit-pm needs every
# event to have a resource.
UNKNOWN_RESOURCE = 'unknown'


class EventLogError(ValueError):
    """The event log cannot be used; the message is meant for the user."""


# --- files ------------------------------------------------------------------------

_stamp_lock = threading.Lock()
_last_stamp = 0


def _stamps_in_use(folders):
    """Timestamps already used as a file-name prefix in ``folders``."""
    used = set()
    for folder in folders:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            # "<stamp>_..." (uploads, models, parameters) or "simulation_<stamp>_...".
            for part in name.split('_')[:2]:
                if part.isdigit():
                    used.add(int(part))
                    break
    return used


def unique_timestamp():
    """A Unix timestamp that no file of this installation has in its name yet.

    Uploaded logs, models, parameter files and simulation logs are all named
    after the second they were created in. Two requests served in the same
    second would otherwise write, and later delete, each other's files.
    """
    global _last_stamp
    folders = (current_app.config['UPLOAD_FOLDER'], current_app.config['SIMULATION_FOLDER'])
    with _stamp_lock:
        stamp = max(int(time.time()), _last_stamp + 1)
        used = _stamps_in_use(folders)
        while stamp in used:
            stamp += 1
        _last_stamp = stamp
    return stamp


def remove_file(folder, filename):
    """Delete ``filename`` from ``folder`` if it is there. Never raises."""
    if not filename:
        return
    try:
        os.unlink(os.path.join(folder, filename))
    except OSError:
        pass


def write_json_atomic(path, payload):
    """Write ``payload`` to ``path`` so that readers never see half a file."""
    temporary = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        with open(temporary, 'w') as handle:
            json.dump(payload, handle, indent=4)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# --- event log ----------------------------------------------------------------------


def _is_missing(value):
    """No value: absent, NaN/NaT (logs built from a table), or a blank string."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(value != value)  # true only for NaN and NaT
    except Exception:
        return False


def normalize_event_log(log):
    """Make ``log`` usable by prosit-pm; return it with notes for the user.

    prosit-pm reads a start timestamp and a resource from every event. Many
    logs carry only the completion timestamp, or no resource: instead of
    failing on them, the missing values are filled with the only neutral
    choice available and the user is told what that means for the simulation.

    Raises ``EventLogError`` when the log has nothing to learn from.
    """
    if any(len(trace) == 0 for trace in log):
        log = pm4py.filter_log(lambda trace: len(trace) > 0, log)
    if len(log) == 0:
        raise EventLogError('The event log contains no events.')

    events = without_start = without_resource = 0
    for trace in log:
        for event in trace:
            events += 1
            if _is_missing(event.get('concept:name')):
                raise EventLogError('Some events have no activity name (concept:name).')
            if _is_missing(event.get('time:timestamp')):
                raise EventLogError('Some events have no timestamp (time:timestamp).')
            if _is_missing(event.get('start:timestamp')):
                event['start:timestamp'] = event['time:timestamp']
                without_start += 1
            if _is_missing(event.get('org:resource')):
                event['org:resource'] = UNKNOWN_RESOURCE
                without_resource += 1

    notes = []
    if without_start == events:
        notes.append(
            'The event log has no start timestamps: every activity is treated as instantaneous '
            '(start = end), so execution times are zero and all the time between events is waiting time.'
        )
    elif without_start:
        notes.append(
            f'{without_start} of {events} events have no start timestamp: '
            f'for them the end timestamp is used as the start.'
        )
    if without_resource == events:
        notes.append(
            f'The event log has no resources: every event was assigned to a single resource named '
            f'"{UNKNOWN_RESOURCE}", which works on one task at a time. Raise its max concurrency in the '
            f'Resources tab if activities can run in parallel.'
        )
    elif without_resource:
        notes.append(
            f'{without_resource} of {events} events have no resource: '
            f'they were assigned to a resource named "{UNKNOWN_RESOURCE}".'
        )
    return log, notes


# A <date .../> attribute, and seconds with a fraction inside it.
_DATE_ELEMENT = re.compile(rb'<date\b[^>]*>')
_SECONDS_FRACTION = re.compile(rb'(T\d{2}:\d{2}:\d{2})\.(\d+)')


def _fraction_of_three_or_six_digits(match):
    digits = match.group(2)[:6]
    return match.group(1) + b'.' + digits.ljust(3 if len(digits) <= 3 else 6, b'0')


def _events_lack_timestamps(log):
    return any('time:timestamp' not in event or 'start:timestamp' not in event
               for trace in log for event in trace)


def _import_xes(xes_path):
    """Read an XES file, whatever the precision of its timestamps.

    pm4py parses a timestamp with ``datetime.fromisoformat``. Before Python
    3.11 that accepts only three or six decimals of a second, and pm4py drops
    without a word any timestamp written otherwise (with nanoseconds, or with
    tenths): the events come back with no time at all. When that may have
    happened, the file is read again from a copy whose fractions are rewritten
    with three or six digits.
    """
    log = xes_importer.apply(xes_path)
    if sys.version_info >= (3, 11) or not _events_lack_timestamps(log):
        return log

    rewritten = False
    with tempfile.NamedTemporaryFile(suffix='.xes', delete=False) as copy:
        try:
            with open(xes_path, 'rb') as original:
                for line in original:
                    fixed = _DATE_ELEMENT.sub(
                        lambda date: _SECONDS_FRACTION.sub(_fraction_of_three_or_six_digits, date.group(0)), line,
                    )
                    rewritten = rewritten or fixed != line
                    copy.write(fixed)
            copy.close()
            # Nothing to rewrite: the log simply has events without timestamps.
            return xes_importer.apply(copy.name) if rewritten else log
        finally:
            copy.close()
            os.unlink(copy.name)


def load_event_log(xes_path):
    """Read an XES file and normalize it. Returns ``(log, notes)``."""
    try:
        log = _import_xes(xes_path)
    except Exception as exc:
        logger.exception("Could not parse %s as XES", xes_path)
        raise EventLogError(f'The file is not a valid XES event log ({describe_exception(exc)}).') from exc
    return normalize_event_log(log)


# --- session ------------------------------------------------------------------------


def load_session_prosit(session, *, with_event_log=False, compute_metrics=False, render=False):
    """Build a fresh ProSiTIntegration for a session.

    Replays the saved Petri net (PNML) and optionally re-imports the XES event
    log. Every request gets its own isolated instance.

    The net is not drawn unless ``render`` is set: the drawing made at
    discovery is stored with the session, and drawing it again costs an
    external Graphviz run on every request.
    """
    metadata = session.get_parameters() or {}
    pnml_filename = metadata.get('pnml_filename')
    if not pnml_filename:
        raise FileNotFoundError(
            'No Petri net (PNML) is associated with this session. Run discovery first.'
        )

    pnml_path = os.path.join(current_app.config['UPLOAD_FOLDER'], pnml_filename)
    if not os.path.exists(pnml_path):
        raise FileNotFoundError(f'PNML file not found: {pnml_filename}')

    instance = ProSiTIntegration()
    if with_event_log:
        xes_path = os.path.join(current_app.config['UPLOAD_FOLDER'], session.filename)
        if not os.path.exists(xes_path):
            raise FileNotFoundError(f'XES file not found: {session.filename}')
        instance.event_log, _ = load_event_log(xes_path)

    instance.import_petri_net_from_pnml(pnml_path, compute_metrics=compute_metrics, render=render)
    return instance


def save_petri_net_pnml(net, initial_marking, final_marking, pnml_filename):
    """Persist a Petri net under the upload folder as ``pnml_filename``."""
    pnml_path = os.path.join(current_app.config['UPLOAD_FOLDER'], pnml_filename)
    pm4py.write_pnml(net, initial_marking, final_marking, pnml_path)
