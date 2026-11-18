"""The description of a Petri net that the page draws (``prosit_tool.petri_dot``)."""

import html
import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.petri_net.utils import petri_utils

from prosit_tool.petri_dot import petri_net_to_dot, quote

VIZ = Path(__file__).resolve().parents[1] / 'prosit_tool' / 'static' / 'vendor' / 'viz-js' / 'viz.js'

NASTY = 'Check "A" & <b>B</b> \\N ok'


def build(order=None, labels=None, tokens=1):
    """start -> A -> p1 -> (B | silent skip) -> p2 -> C -> end.

    ``order`` shuffles the order in which nodes and arcs are added to the net,
    which is the order pm4py would otherwise keep them in.
    """
    labels = labels or {'A': 'A', 'B': 'B', 'C': 'C'}
    places = {name: PetriNet.Place(name) for name in ('start', 'p1', 'p2', 'end')}
    transitions = {
        't_a': PetriNet.Transition('t_a', labels['A']),
        't_b': PetriNet.Transition('t_b', labels['B']),
        'skip': PetriNet.Transition('skip', None),
        't_c': PetriNet.Transition('t_c', labels['C']),
    }
    arcs = [('start', 't_a'), ('t_a', 'p1'), ('p1', 't_b'), ('t_b', 'p2'),
            ('p1', 'skip'), ('skip', 'p2'), ('p2', 't_c'), ('t_c', 'end')]
    place_items, transition_items = list(places.values()), list(transitions.values())
    if order is not None:
        rng = random.Random(order)
        for items in (place_items, transition_items, arcs):
            rng.shuffle(items)

    net = PetriNet('net')
    for place in place_items:
        net.places.add(place)
    for transition in transition_items:
        net.transitions.add(transition)
    nodes = {**places, **transitions}
    for source, target in arcs:
        petri_utils.add_arc_from_to(nodes[source], nodes[target], net)
    return net, Marking({places['start']: tokens}), Marking({places['end']: 1})


def node_line(dot, node_id):
    (line,) = [line for line in dot.splitlines() if line.strip().startswith(f'{node_id} [')]
    return line


# --- what is in the description --------------------------------------------------------

def test_every_node_and_arc_is_described():
    dot, nodes = petri_net_to_dot(*build())

    assert dot.startswith('digraph petri_net {') and dot.rstrip().endswith('}')
    assert sorted(nodes) == ['p0', 'p1', 'p2', 'p3', 't0', 't1', 't2', 't3']
    assert len(re.findall(r'^\s+[pt]\d+ -> [pt]\d+', dot, re.M)) == 8
    for node_id in nodes:
        assert f'id="{node_id}"' in node_line(dot, node_id)


def test_nodes_are_numbered_in_the_order_of_their_names():
    _, nodes = petri_net_to_dot(*build())

    assert [nodes[f't{i}']['name'] for i in range(4)] == ['skip', 't_a', 't_b', 't_c']
    assert [nodes[f'p{i}']['name'] for i in range(4)] == ['end', 'p1', 'p2', 'start']


def test_nodes_say_what_they_are():
    _, nodes = petri_net_to_dot(*build())

    assert nodes['t0'] == {'type': 'transition', 'name': 'skip', 'label': None, 'silent': True}
    assert nodes['t1'] == {'type': 'transition', 'name': 't_a', 'label': 'A', 'silent': False}
    assert nodes['p3'] == {'type': 'place', 'name': 'start', 'initial': 1, 'final': 0}
    assert nodes['p0'] == {'type': 'place', 'name': 'end', 'initial': 0, 'final': 1}
    json.dumps(nodes)   # goes into the answer of the API as it is


@pytest.mark.parametrize('seed', range(5))
def test_the_same_net_gives_the_same_text_however_it_is_stored(seed):
    """The layout must not change between one visit and the next."""
    reference = petri_net_to_dot(*build())

    assert petri_net_to_dot(*build(order=seed)) == reference


# --- what the page relies on ---------------------------------------------------------------

def test_transitions_can_be_found_and_told_apart_in_the_drawing():
    dot, _ = petri_net_to_dot(*build())

    assert 'class="pn-transition"' in node_line(dot, 't1') and 'label="A"' in node_line(dot, 't1')
    silent = node_line(dot, 't0')
    assert 'class="pn-transition pn-silent"' in silent and 'label=""' in silent
    assert 'class="pn-place"' in node_line(dot, 'p1')


def test_markings_are_drawn():
    dot, _ = petri_net_to_dot(*build())

    start, end = node_line(dot, 'p3'), node_line(dot, 'p0')
    assert 'label="\u25cf"' in start and 'pn-initial' in start
    assert 'shape="doublecircle"' in end and 'label="\u25a0"' in end and 'pn-final' in end


def test_several_tokens_are_shown_as_their_number():
    dot, nodes = petri_net_to_dot(*build(tokens=3))

    assert 'label="3"' in node_line(dot, 'p3')
    assert nodes['p3']['initial'] == 3


def test_a_net_without_markings_is_described_too():
    net, _, _ = build()

    dot, nodes = petri_net_to_dot(net)

    assert all(node.get('initial', 0) == 0 and node.get('final', 0) == 0 for node in nodes.values())
    assert 'doublecircle' not in dot


def test_arc_weights_above_one_are_written_on_the_arc():
    net, initial, final = build()
    for arc in net.arcs:
        if arc.source.name == 'start':
            arc.weight = 2

    dot, _ = petri_net_to_dot(net, initial, final)

    assert 'p3 -> t1 [label="2"];' in dot
    assert dot.count('[label="2"]') == 1


# --- labels -----------------------------------------------------------------------------------

def test_quotes_and_backslashes_cannot_break_the_text():
    assert quote('plain') == '"plain"'
    assert quote('say "hi"') == r'"say \"hi\""'
    # a backslash would start an escape (\N is "the name of this node")
    assert quote(r'C:\New') == r'"C:\\New"'
    assert quote('two\nlines') == r'"two\nlines"'


def test_label_outside_ascii_gets_room_for_its_characters():
    """Graphviz in the browser counts every such character as a space."""
    dot, _ = petri_net_to_dot(*build(labels={'A': 'Verifica qualit\u00e0', 'B': '\u5ba1\u6838\u8ba2\u5355', 'C': 'C'}))

    widths = {node_id: re.search(r'width="([\d.]+)"', node_line(dot, node_id)) for node_id in ('t1', 't2', 't3')}
    assert float(widths['t1'].group(1)) > 1.2       # 17 Latin characters
    assert float(widths['t2'].group(1)) > 0.9       # 4 wide characters
    assert widths['t3'] is None                     # plain ASCII: Graphviz knows its width


# --- drawn by the library the page uses ----------------------------------------------------------

@pytest.fixture(scope='module')
def render_svg():
    """Draw DOT text with the Graphviz the page uses (needs Node.js)."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')

    script = (
        "import { readFileSync } from 'node:fs';"
        f"const {{ instance }} = await import({json.dumps(VIZ.as_uri())});"
        "const result = (await instance()).render(readFileSync(0, 'utf8'), { format: 'svg' });"
        "if (result.status !== 'success') { console.error(JSON.stringify(result.errors)); process.exit(1); }"
        "process.stdout.write(result.output);"
    )

    def _render(dot):
        done = subprocess.run([node, '--input-type=module', '-e', script], input=dot,
                              capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr
        return done.stdout

    probe = subprocess.run([node, '--input-type=module', '-e', script], input='digraph { a }',
                           capture_output=True, text=True, timeout=120)
    if probe.returncode != 0:
        pytest.skip('this Node.js cannot load the drawing library')
    return _render


def test_the_description_is_drawn_with_every_node_findable(render_svg):
    dot, nodes = petri_net_to_dot(*build(labels={'A': NASTY, 'B': "O'Neil's review", 'C': 'Pay & close'}))

    svg = render_svg(dot)

    groups = {match.group(1): html.unescape(match.group(2)) for match in re.finditer(r'<g id="([^"]+)" class="([^"]+)"', svg)}
    for node_id, node in nodes.items():
        assert node_id in groups, node_id
        expected = 'pn-place' if node['type'] == 'place' else 'pn-transition'
        assert expected in groups[node_id].split()
    assert 'pn-silent' in groups['t0'].split()
    assert len(re.findall(r'class="edge"', svg)) == 8


def test_labels_are_drawn_as_they_are_written(render_svg):
    dot, _ = petri_net_to_dot(*build(labels={'A': NASTY, 'B': "O'Neil's review", 'C': 'Pay & close'}))

    svg = render_svg(dot)

    texts = {html.unescape(text) for text in re.findall(r'<text[^>]*>([^<]*)</text>', svg)}
    assert {NASTY, "O'Neil's review", 'Pay & close'} <= texts
    assert '<b>' not in svg and '<script' not in svg
