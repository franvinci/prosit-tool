"""The JavaScript of the page: served so that a browser accepts it, wired
consistently, and unit-tested.

There is no build step, so nothing else checks that a module imports names
that exist or that a button names an action somebody handles: a mistake there
would only show up as a control that silently does nothing.
"""

import json
import mimetypes
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from prosit_tool.app import create_app
from prosit_tool.format_converters import distribution_from_prosit, distribution_to_prosit

REPO = Path(__file__).resolve().parents[1]
STATIC_JS = REPO / 'prosit_tool' / 'static' / 'js'
TEMPLATES = REPO / 'prosit_tool' / 'templates'
ENTRY = STATIC_JS / 'app.js'
MODULES = sorted(STATIC_JS.rglob('*.js'))
PAGES = sorted(TEMPLATES.glob('*.html'))

IMPORT = re.compile(r"^import\s*\{([^}]*)\}\s*from\s*'([^']+)';", re.M | re.S)
SIDE_EFFECT_IMPORT = re.compile(r"^import\s*'([^']+)';", re.M)
EXPORT = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)
INLINE_HANDLER = re.compile(r"""\bon[a-z]+\s*=\s*\\?["']""")
ACTION_IN_MARKUP = re.compile(r'data-action="([a-z][a-z0-9-]*)"')
ACTIONS_HANDLED = re.compile(r"\bon\('(?:click|change|input)',\s*\{(.*?)\n\}\);|\bon\('(?:click|change|input)',\s*\{([^\n]*)\}\);", re.S)
ACTION_NAME = re.compile(r"'([a-z][a-z0-9-]*)'\s*:")


def _imports(module):
    """``(names, target file)`` for every import of ``module``."""
    text = module.read_text()
    found = [([name.strip() for name in names.split(',') if name.strip()], spec)
             for names, spec in IMPORT.findall(text)]
    found += [([], spec) for spec in SIDE_EFFECT_IMPORT.findall(text)]
    return [(names, spec, (module.parent / spec).resolve()) for names, spec in found]


# --- served the way a browser needs ------------------------------------------------------

def test_page_loads_the_entry_module_and_has_no_script_of_its_own(client):
    page = client.get('/').get_data(as_text=True)

    assert '<script type="module" src="/static/js/app.js"></script>' in page
    inline = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>', page)
    assert inline == []


def test_modules_and_style_sheet_are_served_with_their_type(client):
    assert client.get('/static/js/app.js').mimetype == 'text/javascript'
    assert client.get('/static/js/features/params/tree-editor.js').mimetype == 'text/javascript'
    assert client.get('/static/css/style.css').mimetype == 'text/css'


def test_script_type_does_not_depend_on_the_system(tmp_path):
    """On Windows the registry can say that .js is plain text; browsers refuse such modules."""
    mimetypes.add_type('text/plain', '.js')
    try:
        assert mimetypes.guess_type('app.js')[0] == 'text/plain'
        client = create_app(tmp_path / 'data', testing=True).test_client()
        assert client.get('/static/js/app.js').mimetype == 'text/javascript'
    finally:
        mimetypes.add_type('text/javascript', '.js')


# --- wired consistently --------------------------------------------------------------------

def test_every_import_names_a_module_and_something_it_exports():
    problems = []
    for module in MODULES:
        for names, spec, target in _imports(module):
            where = module.relative_to(STATIC_JS)
            if not spec.startswith(('./', '../')) or not spec.endswith('.js'):
                problems.append(f"{where}: '{spec}' must be a relative path ending in .js")
            elif not target.is_file():
                problems.append(f"{where}: '{spec}' does not exist")
            else:
                exported = set(EXPORT.findall(target.read_text()))
                problems += [f"{where}: '{spec}' does not export {name}" for name in names if name not in exported]
    assert problems == []


def test_every_module_is_loaded_by_the_page():
    loaded, queue = set(), [ENTRY]
    while queue:
        module = queue.pop()
        if module in loaded:
            continue
        loaded.add(module)
        queue += [target for _, _, target in _imports(module)]
    assert sorted(set(MODULES) - loaded) == []


def test_no_inline_event_handlers():
    """Handlers written in the markup are how a name with a quote used to break the page."""
    offenders = [str(path.relative_to(REPO)) for path in PAGES + MODULES if INLINE_HANDLER.search(path.read_text())]
    assert offenders == []


def test_every_action_of_the_markup_is_handled_and_every_handler_is_used():
    used, handled = set(), set()
    for path in PAGES + MODULES:
        text = path.read_text()
        used.update(ACTION_IN_MARKUP.findall(text))
        for multi_line, single_line in ACTIONS_HANDLED.findall(text):
            handled.update(ACTION_NAME.findall(multi_line or single_line))

    assert len(handled) > 40
    assert sorted(used - handled) == [], 'marked in the page but handled by nobody'
    assert sorted(handled - used) == [], 'handled but never marked in the page'


# --- unit tests --------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def node():
    """A Node.js able to load the modules as they are (any current release)."""
    executable = shutil.which('node')
    if executable is None:
        pytest.skip('Node.js is not installed: the JavaScript unit tests need it')
    probe = subprocess.run(
        [executable, '--input-type=module', '-e', f"await import({json.dumps((STATIC_JS / 'core' / 'state.js').as_uri())})"],
        capture_output=True, text=True, timeout=60,
    )
    if probe.returncode != 0:
        pytest.skip('this Node.js cannot load .js files as ES modules (needs 20.19+ or 22.7+)')
    return executable


def test_javascript_unit_tests(node):
    result = subprocess.run([node, '--test', 'tests/js'], cwd=REPO, capture_output=True, text=True, timeout=300)

    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert re.search(r'^# fail 0$', result.stdout, re.M)
    assert int(re.search(r'^# pass (\d+)$', result.stdout, re.M).group(1)) >= 60


LEAVES = [
    ('expon', [20.0, 14.6]),
    ('expon', [0.0, 30.59]),
    ('uniform', [10.0, 20.0]),
    ('norm', [12.0, 3.0]),
    ('lognorm', [0.4, 1.0, 20.0]),
    ('gamma', [4.0, -2.0, 3.0]),
    ('gamma', [1673.47, -313.08, 0.19737]),
    ('fixed', [7.0]),
]


def test_tree_leaf_shown_by_the_editor_is_saved_back_unchanged(node):
    """The editor (JavaScript) and the server (Python) convert leaf parameters
    in opposite directions: what one shows, the other must turn back into the
    parameters it started from.
    """
    module = (STATIC_JS / 'features' / 'params' / 'distributions.js').as_uri()
    script = (
        f"const {{ leafParamsFromProsit }} = await import({json.dumps(module)});"
        f"const leaves = {json.dumps(LEAVES)};"
        "console.log(JSON.stringify(leaves.map(([family, params]) => leafParamsFromProsit(family, params, {}))));"
    )
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    shown_by_editor = json.loads(result.stdout)

    for (family, params), shown in zip(LEAVES, shown_by_editor):
        # the same quantities the server computes for a plain distribution...
        by_server = distribution_from_prosit(family, params, 0, 1000, 0)
        assert shown == pytest.approx({key: by_server[key] for key in shown}), family
        # ...and, saved, the parameters prosit-pm had.
        saved = distribution_to_prosit(family, {**shown, 'min_value': -1000, 'max_value': 1000})
        assert saved['params'] == pytest.approx(params, rel=1e-9), family


# --- the features a split can test, against the simulator itself ---------------------------

def _weight(value):
    return {'value': value}


def _time(minutes):
    return {'value': minutes, 'dist': {'dist_name': 'fixed', 'params': [minutes], 'min_value': minutes, 'max_value': minutes}}


def _split(feature, when_at_most, when_above):
    return {'0': {'feature': feature, 'threshold': 0.5, 'children': {'true': 1, 'false': 2}},
            '1': when_at_most, '2': when_above}


def _with_split_everywhere(parameters, tree_type, feature):
    """A copy of ``parameters`` where every tree of ``tree_type`` is one split on ``feature``."""
    changed = json.loads(json.dumps(parameters))
    if tree_type == 'transition':
        weights = changed['transition_params']['transition_weights']
        for name in weights:
            weights[name] = _split(feature, _weight(0.6), _weight(0.4))
    elif tree_type == 'resource':
        weights = changed['resource_params']['resource_weights']
        for name in weights:
            weights[name] = _split(feature, _weight(0.6), _weight(0.4))
    elif tree_type == 'arrival':
        changed['inter_arrival_params']['inter_arrival_time']['distribution'] = _split(feature, _time(30), _time(45))
    elif tree_type == 'execution':
        durations = changed['execution_time_params']['activity_durations']
        for name in durations:
            durations[name] = _split(feature, _time(5), _time(7))
    elif tree_type == 'waiting':
        waiting = changed['waiting_time_params']['resource_waiting_times']
        for name in waiting:
            waiting[name] = _split(feature, _time(1), _time(2))
    return changed


@pytest.mark.parametrize('workload', [False, True], ids=['plain', 'with workload features'])
def test_every_feature_offered_for_a_split_is_one_the_simulator_provides(client, discovered, tmp_path, node, workload):
    """The dialog that adds a split lists features per kind of tree (tree-features.js).
    A feature the simulator does not compute for that kind of tree would make every
    simulation of the scenario fail: each one offered is tried on a real simulation.
    """
    from .conftest import event_rows, write_xes

    rows = event_rows(activities=('A', 'B', 'C'), cases=12, resources=('r1', 'r2'))
    for row in rows:
        case = int(row['case:concept:name'][1:])
        row['case:kind'] = 'gold' if case % 2 else 'silver'
        row['case:amount'] = 10.0 + case * 3
    query = '?max_depth_tree=1' + ('&use_workload_features=1' if workload else '')
    session_id, body = discovered(write_xes(rows, tmp_path / 'log.xes'), query)
    parameters = body['parameters']
    assert parameters['model_options'] == {'rules_mode': True, 'use_workload_features': workload}

    saved = tmp_path / 'parameters.json'
    saved.write_text(json.dumps(parameters))
    module = (STATIC_JS / 'features' / 'params' / 'tree-features.js').as_uri()
    script = (
        "import { readFileSync } from 'node:fs';"
        f"const {{ generateFeaturesForTreeType }} = await import({json.dumps(module)});"
        f"const parameters = JSON.parse(readFileSync({json.dumps(str(saved))}, 'utf8'));"
        "const types = ['transition', 'resource', 'arrival', 'execution', 'waiting'];"
        "console.log(JSON.stringify(Object.fromEntries(types.map(type =>"
        " [type, generateFeaturesForTreeType(type, parameters).map(feature => feature.value)]))));"
    )
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    offered = json.loads(result.stdout)

    # the log has what every kind of feature needs
    assert 'case:kind = gold' in offered['transition'] and 'case:amount' in offered['transition']
    assert ('workload' in offered['waiting']) is workload
    assert {len(features) > 0 for features in offered.values()} == {True}

    run_id = client.post(f'/api/sessions/{session_id}/runs', json={'name': 'Splits'}).get_json()['run']['id']
    refused = []
    for tree_type, features in offered.items():
        for feature in features:
            edited = _with_split_everywhere(parameters, tree_type, feature)
            saved_run = client.put(f'/api/runs/{run_id}', json={'parameters': edited})
            assert saved_run.status_code == 200, (tree_type, feature, saved_run.data)
            simulated = client.post(f'/api/runs/{run_id}/simulate', json={'num_instances': 4})
            if simulated.status_code != 200:
                refused.append(f'{tree_type}: {feature}')
    assert refused == []
