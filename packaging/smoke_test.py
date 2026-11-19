#!/usr/bin/env python3
"""Start a packaged ProSiT and take it through a whole session.

This is how what gets released is checked: the executable built by PyInstaller,
the ``prosit-tool`` command of an installed wheel, the Docker image. It needs
nothing but the standard library, so any Python can run it:

    python packaging/smoke_test.py dist/prosit-tool/prosit-tool
    python packaging/smoke_test.py prosit-tool
    python packaging/smoke_test.py python -m prosit_tool
    python packaging/smoke_test.py --url http://localhost:5050     (already running)

The program is started on a free port with an empty data directory of its own.
A small event log is uploaded, the model and its parameters are discovered
(following the progress, as the page does), a simulation is run and its results
are read back. The first thing that does not work ends the test with exit
status 1 and the output of the program.
"""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

APP_NAME = 'prosit-tool'
HOST = '127.0.0.1'

# No proxy: a proxy configured in the environment must not be asked to reach
# a server on this machine.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Failure(Exception):
    """Something the packaged program should do and does not."""


def expect(condition, message):
    if not condition:
        raise Failure(message)


def passed(message):
    print(f'  ok  {message}', flush=True)


# --- the event log ------------------------------------------------------------------------

def example_log(cases=40):
    """A small XES log: a choice, five resources, a numeric attribute."""
    def stamp(moment):
        return moment.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')

    people = {
        'Register': ('anna', 'bob'), 'Check': ('carl', 'dana'), 'Fast check': ('carl', 'dana'),
        'Decide': ('erin',), 'Pay': ('anna',), 'Reject': ('bob',),
    }
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<log xes.version="1.0" xes.features="nested-attributes" xmlns="http://www.xes-standard.org/">',
    ]
    first_monday = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    for case in range(cases):
        day, slot = divmod(case, 4)
        clock = first_monday + timedelta(days=day + 2 * (day // 5), hours=2 * slot)
        path = ['Register', 'Fast check' if case % 3 == 0 else 'Check', 'Decide', 'Reject' if case % 4 == 0 else 'Pay']
        lines += ['  <trace>', f'    <string key="concept:name" value="case-{case:03d}"/>']
        for position, activity in enumerate(path):
            clock += timedelta(minutes=5 + (case * 7 + position * 3) % 20)       # waiting
            start = clock
            clock += timedelta(minutes=10 + (case * 5 + position * 11) % 25)     # working
            resource = people[activity][case % len(people[activity])]
            lines += [
                '    <event>',
                f'      <string key="concept:name" value="{activity}"/>',
                f'      <string key="org:resource" value="{resource}"/>',
                f'      <date key="start:timestamp" value="{stamp(start)}"/>',
                f'      <date key="time:timestamp" value="{stamp(clock)}"/>',
                f'      <int key="amount" value="{100 + (case * 37) % 900}"/>',
                '    </event>',
            ]
        lines.append('  </trace>')
    lines.append('</log>')
    return '\n'.join(lines).encode('utf-8')


# --- talking to the program ---------------------------------------------------------------------

def call(base, path, method='GET', body=None, headers=None, timeout=900):
    """``(status, content type, bytes)`` of the answer, also when it is an error."""
    request = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.status, response.headers.get('Content-Type', ''), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get('Content-Type', ''), error.read()


def call_json(base, path, method='GET', payload=None, **kwargs):
    """The JSON answer of a request that must succeed."""
    body = headers = None
    if payload is not None:
        body, headers = json.dumps(payload).encode('utf-8'), {'Content-Type': 'application/json'}
    status, _, raw = call(base, path, method, body, headers, **kwargs)
    try:
        answer = json.loads(raw)
    except ValueError:
        raise Failure(f'{method} {path}: the answer ({status}) is not JSON: {raw[:200]!r}') from None
    expect(status == 200, f'{method} {path} answered {status}: {answer}')
    return answer


def upload(base, filename, content):
    boundary = uuid.uuid4().hex
    body = b''.join([
        f'--{boundary}\r\n'.encode(),
        f'Content-Disposition: form-data; name="xes_file"; filename="{filename}"\r\n'.encode(),
        b'Content-Type: application/xml\r\n\r\n',
        content,
        f'\r\n--{boundary}--\r\n'.encode(),
    ])
    status, _, raw = call(base, '/api/upload', 'POST', body,
                          {'Content-Type': f'multipart/form-data; boundary={boundary}'})
    expect(status == 200, f'the upload answered {status}: {raw[:300]!r}')
    return json.loads(raw)


# --- the session ------------------------------------------------------------------------------------

def exercise(base, log_name, log_content, expected_version=None, activities=()):
    health = call_json(base, '/api/health', timeout=30)
    expect(health.get('app') == APP_NAME, f'this is not ProSiT: {health}')
    if expected_version:
        expect(health.get('version') == expected_version,
               f'version {health.get("version")} is running, {expected_version} was expected')
    passed(f'ProSiT {health.get("version")} answers')

    status, _, page = call(base, '/')
    expect(status == 200 and b'js/app.js' in page, f'the page is not served ({status})')
    assets = {
        '/static/js/app.js': ('text/javascript', 200),
        '/static/js/features/discovery-progress.js': ('text/javascript', 500),
        '/static/css/style.css': ('text/css', 2000),
        '/static/vendor/bootstrap/bootstrap.min.css': ('text/css', 100_000),
        '/static/vendor/bootstrap/bootstrap.bundle.min.js': ('text/javascript', 50_000),
        '/static/vendor/chart.js/chart.umd.js': ('text/javascript', 100_000),
        '/static/vendor/viz-js/viz.js': ('text/javascript', 500_000),
    }
    for path, (kind, smallest) in assets.items():
        status, content_type, content = call(base, path)
        expect(status == 200, f'{path} is missing from the package ({status})')
        expect(content_type.startswith(kind), f'{path} is served as {content_type!r}, the browser needs {kind}')
        expect(len(content) >= smallest, f'{path} is only {len(content)} bytes')
    passed('the page, its scripts and the libraries it draws with are served')

    session_id = upload(base, log_name, log_content)['session_id']
    passed(f'an event log is uploaded (session {session_id})')

    # The discovery, followed the way the page follows it.
    outcome, reports = {}, []

    def discover():
        try:
            outcome['answer'] = call_json(base, f'/api/discover/{session_id}?max_depth_tree=1', 'POST')
        except Exception as error:  # reported below, in the main thread
            outcome['error'] = error

    worker = threading.Thread(target=discover, daemon=True)
    worker.start()
    while worker.is_alive():
        try:
            report = call_json(base, f'/api/discover/{session_id}/progress', timeout=60)
        except Failure:
            report = {}
        if report.get('in_progress'):
            reports.append(report)
        time.sleep(0.05)
    worker.join()
    if 'error' in outcome:
        raise outcome['error']
    discovered = outcome['answer']
    model = discovered['parameters']['process_model']
    expect(model['dot'].startswith('digraph'), 'the discovered model has no drawing')
    expect(model['activities'] and set(activities) <= set(model['activities']),
           f'activities are missing: {model["activities"]}')
    expect(discovered['parameters']['resource_params']['resources'], 'no resource was discovered')
    # A program that cannot start its worker processes still discovers, more
    # slowly, and says so: here that is a fault of the package.
    slowly = [warning for warning in discovered.get('warnings', []) if 'fitted by one process' in warning]
    expect(not slowly, ' '.join(slowly))
    passed(f'the model and its parameters are discovered ({len(model["activities"])} activities, '
           f'fitness {model["fitness"]:.2f})')
    # How many steps are caught depends on how fast the machine is: one is enough
    # to know that the program answers while it works.
    steps = list(dict.fromkeys(report['label'] for report in reports))
    expect(steps, 'the progress of the discovery was never reported')
    percents = [report['percent'] for report in reports]
    expect(percents == sorted(percents), 'the progress went backwards')
    passed(f'its progress is reported (up to {percents[-1]:.0f}%; seen: {", ".join(steps)})')

    parameters = call_json(base, f'/api/parameters/{session_id}')['parameters']
    expect(parameters['transition_params']['transition_weights'], 'the stored parameters cannot be read back')
    passed('the parameters are read back')

    simulated = call_json(base, f'/api/simulate/{session_id}', 'POST', {'num_instances': 25})
    expect(simulated['num_events'] > 0, 'the simulation produced no event')
    passed(f'a simulation runs ({simulated["num_events"]} events)')

    process_map = call_json(base, f'/api/get_visualization/{session_id}/process_map')
    expect(process_map['dot'].startswith('digraph'), 'the process map is not described')
    for chart in ('case_duration_dist', 'resource_heatmap', 'activity_duration_boxplot', 'waiting_time_dist'):
        status, _, raw = call(base, f'/api/get_visualization/{session_id}/{chart}')
        expect(status == 200, f'the {chart} chart answered {status}: {raw[:200]!r}')
    passed('the results are computed')

    metrics = call_json(base, f'/api/metrics/{session_id}', 'POST')['prosit_metrics']
    expect({'control-flow', 'time', 'resource-flow'} <= set(metrics), f'accuracy metrics are missing: {sorted(metrics)}')
    passed('the accuracy of the model is measured')

    filename = simulated['sim_output_filename']
    status, _, table = call(base, f'/api/download/{filename}')
    expect(status == 200 and table.count(b'\n') > 1, f'the simulated log cannot be downloaded as CSV ({status})')
    status, _, xes = call(base, f'/api/download_xes/{filename}')
    expect(status == 200 and b'<log' in xes[:2000], f'the simulated log cannot be downloaded as XES ({status})')
    passed('the simulated log is downloaded as CSV and as XES')

    sessions = call_json(base, '/api/sessions')['sessions']
    expect(any(session['id'] == session_id for session in sessions), 'the session is not listed')
    call_json(base, f'/api/sessions/{session_id}', 'DELETE')
    passed('the session is listed, then deleted')


# --- the program -------------------------------------------------------------------------------------

def free_port():
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def wait_until_it_answers(base, process, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Failure(f'the program stopped at start-up with exit status {process.returncode}')
        try:
            if call(base, '/api/health', timeout=5)[0] == 200:
                return
        except OSError:
            pass  # not listening yet
        time.sleep(0.5)
    raise Failure(f'the program did not answer within {seconds} seconds')


def check_workers(command, seconds):
    """The program starts a worker process and gives it a job.

    That is how a discovery fits its models on every processor, and what an
    executable has to do in a way of its own.
    """
    try:
        check = subprocess.run(command + ['--check-workers'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=seconds)
    except subprocess.TimeoutExpired:
        raise Failure(f'asked to start a worker process, the program did not answer within {seconds:.0f} seconds')
    said = check.stdout.decode('utf-8', 'replace').strip()
    expect(check.returncode == 0, f'the program cannot start a worker process:\n{said}')
    passed('it starts worker processes')


def stop(process):
    """Stop the program, the way Ctrl+C does where that can be sent: the program
    then stops the processes it works with, which one that is simply ended
    leaves behind for a while."""
    if process.poll() is not None:
        return
    if os.name == 'posix':
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            pass  # it was started where Ctrl+C is ignored
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=20)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('command', nargs=argparse.REMAINDER,
                        help='how to start ProSiT (an executable, or a command with its arguments)')
    parser.add_argument('--url', help='test a ProSiT that is already running at this address instead')
    parser.add_argument('--log', help='event log to upload (default: a small one made on the spot)')
    parser.add_argument('--expect-version', help='fail if the program is not this version')
    parser.add_argument('--startup-timeout', type=float, default=180,
                        help='seconds to wait for the program to answer (default: %(default)s)')
    args = parser.parse_args(argv)
    if bool(args.command) == bool(args.url):
        parser.error('give either the command that starts ProSiT or --url')

    if args.log:
        with open(args.log, 'rb') as handle:
            log_name, log_content, activities = os.path.basename(args.log), handle.read(), ()
    else:
        log_name, log_content, activities = 'smoke-test.xes', example_log(), ('Register', 'Decide', 'Pay')

    started = time.monotonic()
    process = output = None
    workspace = tempfile.mkdtemp(prefix='prosit-smoke-')
    try:
        if args.url:
            base = args.url.rstrip('/')
            print(f'Testing the ProSiT running at {base}', flush=True)
        else:
            port = free_port()
            base = f'http://{HOST}:{port}'
            command = args.command + ['--no-browser', '--host', HOST, '--port', str(port),
                                      '--data-dir', os.path.join(workspace, 'data')]
            print('Starting', ' '.join(command), flush=True)
            output = open(os.path.join(workspace, 'output.txt'), 'wb')
            environment = dict(os.environ, PYTHONUNBUFFERED='1')
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, env=environment)
            wait_until_it_answers(base, process, args.startup_timeout)
            passed(f'it starts and listens ({time.monotonic() - started:.1f} s)')
            check_workers(args.command, args.startup_timeout)
        exercise(base, log_name, log_content, args.expect_version, activities)
        if process is not None:
            expect(process.poll() is None, f'the program stopped by itself with exit status {process.returncode}')
    except (Failure, OSError) as failure:
        # OSError: the program cannot be started, or stopped answering half way.
        print(f'\nFAILED: {failure}', flush=True)
        if process is not None:
            stop(process)
            output.close()
            with open(output.name, 'rb') as handle:
                tail = handle.read()[-6000:].decode('utf-8', 'replace')
            print('\n--- last output of the program ---\n' + tail, flush=True)
        return 1
    finally:
        if process is not None:
            stop(process)
        if output is not None and not output.closed:
            output.close()
        shutil.rmtree(workspace, ignore_errors=True)

    print(f'\nEverything works ({time.monotonic() - started:.0f} s).', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
