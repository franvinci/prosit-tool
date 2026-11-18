"""Description of a Petri net in the DOT language of Graphviz.

The page draws the net itself (Graphviz compiled to WebAssembly runs in the
browser), so the server only has to say what to draw. Besides the look, two
things matter:

* the text is stable: the same net always gives the same text, whatever the
  order in which its nodes happen to be stored, and so the same layout every
  time a session is opened;
* every node can be found in the drawing: its id in the DOT text is the id of
  its element in the SVG, and its class says what it is. That is what lets the
  page highlight a transition, or react to a click on it, without drawing the
  net again.
"""

import unicodedata

# What the nodes look like. Kept together so that the look can be read, and
# changed, in one place.
#
# Graphviz sizes a box from the width of its label, and the Graphviz that runs
# in the browser knows the widths of the characters of a few fonts only:
# Helvetica is one of them (and Arial, which browsers use for it, has the same
# widths).
_FONT = 'Helvetica'
_FONT_SIZE = 12
_GRAPH = {'bgcolor': 'white', 'rankdir': 'LR', 'overlap': 'false'}
_NODE = {'fontname': _FONT, 'fontsize': str(_FONT_SIZE), 'style': 'filled', 'fillcolor': 'white', 'fontcolor': 'black'}
_TRANSITION = {'shape': 'box'}
_SILENT = {'shape': 'box', 'fillcolor': '#333333', 'color': '#444444'}
_PLACE = {'shape': 'circle', 'fixedsize': 'true', 'width': '0.75'}
_ONE_TOKEN = '\u25cf'      # a filled circle: the token of the initial marking
_FINAL = '\u25a0'          # a filled square: the place where a case ends


def quote(text):
    """``text`` as a double-quoted DOT string.

    A backslash starts an escape sequence in a DOT label (``\\n`` breaks the
    line, ``\\N`` stands for the name of the node...), so a backslash that is
    part of a name has to be doubled to be shown as it is.
    """
    text = str(text).replace('\\', '\\\\').replace('"', '\\"')
    return '"' + text.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n') + '"'


def _minimum_width(label):
    """Width in inches a box needs for ``label``, or ``None`` to let Graphviz decide.

    Graphviz has no width for the characters outside ASCII and counts each of
    them as a space: a label written in Greek or in Chinese would not fit in
    its box. For such labels the width is estimated here.
    """
    if label.isascii():
        return None
    points = 0.0
    for line in label.splitlines() or ['']:
        width = sum(
            _FONT_SIZE if unicodedata.east_asian_width(char) in ('W', 'F') else _FONT_SIZE * 0.6
            for char in line
        )
        points = max(points, width)
    return f'{points / 72 + 0.3:.2f}'


def _attributes(**values):
    return '[' + ', '.join(f'{name}={quote(value)}' for name, value in values.items()) + ']'


def _by_name(nodes):
    """Nodes in an order that depends only on what they are."""
    return sorted(nodes, key=lambda node: (str(node.name), str(getattr(node, 'label', '') or '')))


def _tokens(marking, place):
    return int(marking.get(place, 0)) if marking else 0


def petri_net_to_dot(net, initial_marking=None, final_marking=None):
    """Describe ``net`` for Graphviz.

    Returns ``(dot, nodes)``: the DOT text, and for each node id used in it
    what the node is::

        {'t0': {'type': 'transition', 'name': ..., 'label': ..., 'silent': False},
         'p0': {'type': 'place', 'name': ..., 'initial': 1, 'final': 0}}

    Transitions are ``t0, t1...`` and places ``p0, p1...``, both numbered in
    the order of their names.
    """
    ids = {}
    nodes = {}
    lines = [
        'digraph petri_net {',
        f'    graph {_attributes(**_GRAPH)};',
        f'    node {_attributes(**_NODE)};',
        f'    edge {_attributes(arrowhead="normal", fontname=_FONT, fontsize=str(_FONT_SIZE))};',
    ]

    for index, transition in enumerate(_by_name(net.transitions)):
        node_id = ids[transition] = f't{index}'
        silent = not transition.label
        nodes[node_id] = {
            'type': 'transition',
            'name': transition.name,
            'label': transition.label or None,
            'silent': silent,
        }
        look = dict(_SILENT if silent else _TRANSITION)
        look.update({
            'id': node_id,
            'class': 'pn-transition pn-silent' if silent else 'pn-transition',
            'label': '' if silent else transition.label,
        })
        width = None if silent else _minimum_width(transition.label)
        if width:
            look['width'] = width
        lines.append(f'    {node_id} {_attributes(**look)};')

    for index, place in enumerate(_by_name(net.places)):
        node_id = ids[place] = f'p{index}'
        initial = _tokens(initial_marking, place)
        final = _tokens(final_marking, place)
        nodes[node_id] = {'type': 'place', 'name': place.name, 'initial': initial, 'final': final}
        look = dict(_PLACE, id=node_id, label='')
        look['class'] = 'pn-place'
        if final:
            look.update({'shape': 'doublecircle', 'label': _FINAL, 'fontsize': '32', 'class': 'pn-place pn-final'})
        if initial:
            # One token is drawn as a token, more as their number.
            look.update({'label': _ONE_TOKEN if initial == 1 else str(initial),
                         'fontsize': '34' if initial == 1 else '18',
                         'class': look['class'] + ' pn-initial'})
        lines.append(f'    {node_id} {_attributes(**look)};')

    arcs = sorted(
        ((ids[arc.source], ids[arc.target], int(getattr(arc, 'weight', 1) or 1)) for arc in net.arcs),
        key=lambda arc: (arc[0][0], int(arc[0][1:]), arc[1][0], int(arc[1][1:])),
    )
    for source, target, weight in arcs:
        label = f' {_attributes(label=str(weight))}' if weight > 1 else ''
        lines.append(f'    {source} -> {target}{label};')

    lines.append('}')
    return '\n'.join(lines) + '\n', nodes
