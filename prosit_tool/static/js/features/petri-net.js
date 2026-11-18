/**
 * The drawing of the Petri net.
 *
 * The server describes the net (DOT text) and says which node of the drawing
 * is which transition or place; the drawing is made here. Each node is an
 * element of its own, so a transition can be highlighted, or clicked to open
 * its editor, without drawing the net again: zoom and position stay where the
 * user left them.
 */

import { escapeHtml, on } from '../core/dom.js';
import { renderDot } from '../core/graphviz.js';
import { state } from '../core/state.js';

// The net on screen: its description, and the element of each transition.
const drawn = {
    dot: null,
    byName: new Map(),      // transition name  -> its element
    byLabel: new Map(),     // activity label   -> the elements of the transitions that carry it
};
// Which drawing was asked for last: an older one that arrives late is dropped.
let requested = 0;
// What to highlight: transitions by name and activities by label. Kept as
// asked, so that it can be applied to a drawing that arrives later.
let wanted = { names: [], labels: [] };
let onTransitionClick = () => {};

/** Call `listener(name)` when a transition of the drawing is clicked, or activated from the keyboard. */
export function onTransitionActivated(listener) {
    onTransitionClick = listener;
}

// ---- pan and zoom ---------------------------------------------------------------------

// The drawing sits in a viewport that is moved and scaled inside a container
// of fixed height, which clips whatever does not fit.
const view = {
    scale: 1, tx: 0, ty: 0,
    dragging: false, moved: false, startX: 0, startY: 0, startTx: 0, startTy: 0,
    naturalW: 0, naturalH: 0,
};
const MIN_SCALE = 0.3;
const MAX_SCALE = 5;
// A press that moves less than this many pixels is a click, not a drag.
const CLICK_TOLERANCE = 4;

function applyTransform() {
    const viewport = document.getElementById('petriNetViewport');
    if (!viewport) return;
    viewport.style.transform = `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})`;
    const slider = document.getElementById('petriNetZoom');
    if (slider) slider.value = view.scale;
}

// Zoom keeping fixed the point of the container at (x, y).
function zoomAt(target, x, y) {
    const scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, target));
    view.tx = x - (x - view.tx) * (scale / view.scale);
    view.ty = y - (y - view.ty) * (scale / view.scale);
    view.scale = scale;
    applyTransform();
}

function setZoom(value) {
    const container = document.getElementById('petriNetContainer');
    const target = parseFloat(value) || 1;
    if (!container) { view.scale = target; applyTransform(); return; }
    zoomAt(target, container.clientWidth / 2, container.clientHeight / 2);
}

// Give the container the height the drawing needs at the width it has, within
// sensible limits for very small and very large nets.
function autoSizeContainer() {
    const container = document.getElementById('petriNetContainer');
    if (!container || !view.naturalW || !view.naturalH || !container.clientWidth) return;
    const height = container.clientWidth * (view.naturalH / view.naturalW);
    container.style.height = Math.max(160, Math.min(500, height + 20)) + 'px';
}

function fitView() {
    const container = document.getElementById('petriNetContainer');
    const viewport = document.getElementById('petriNetViewport');
    if (!container || !viewport) return;
    autoSizeContainer();
    const width = view.naturalW || viewport.scrollWidth || 800;
    const height = view.naturalH || viewport.scrollHeight || 500;
    const padding = 16;
    const fit = Math.min((container.clientWidth - padding * 2) / width, (container.clientHeight - padding * 2) / height, 1);
    view.scale = Math.max(MIN_SCALE, fit);
    view.tx = (container.clientWidth - width * view.scale) / 2;
    view.ty = (container.clientHeight - height * view.scale) / 2;
    applyTransform();
}

function isInSight(element, margin = 0) {
    const container = document.getElementById('petriNetContainer');
    const box = element.getBoundingClientRect();
    const frame = container.getBoundingClientRect();
    return box.left >= frame.left + margin && box.right <= frame.right - margin
        && box.top >= frame.top + margin && box.bottom <= frame.bottom - margin;
}

// Move the drawing, without changing the zoom, so that `element` is in sight.
function reveal(element) {
    const container = document.getElementById('petriNetContainer');
    if (!container || !element) return;
    const box = element.getBoundingClientRect();
    const frame = container.getBoundingClientRect();
    if (!frame.width || !box.width) return;       // the card is hidden
    view.tx += (frame.left + frame.width / 2) - (box.left + box.width / 2);
    view.ty += (frame.top + frame.height / 2) - (box.top + box.height / 2);
    applyTransform();
}

// ---- highlighting ----------------------------------------------------------------------

function applyHighlight() {
    const container = document.getElementById('petriNetContainer');
    if (!container) return;
    const elements = [
        ...wanted.names.map(name => drawn.byName.get(name)).filter(Boolean),
        ...wanted.labels.flatMap(label => drawn.byLabel.get(label) || []),
    ];
    container.querySelectorAll('.pn-highlighted').forEach(element => element.classList.remove('pn-highlighted'));
    elements.forEach(element => element.classList.add('pn-highlighted'));
    // What is highlighted should be seen: if none of it is, go to the first.
    if (elements.length && !elements.some(element => isInSight(element, 8))) reveal(elements[0]);
}

/** Highlight one transition of the net, given its name. */
export function highlightTransition(name) {
    wanted = { names: [name], labels: [] };
    applyHighlight();
}

/** Highlight the transitions that perform the given activities (one label or a list). */
export function highlightActivities(labels) {
    wanted = { names: [], labels: [].concat(labels) };
    applyHighlight();
}

/** Show the net again with no highlight. */
export function clearHighlight() {
    wanted = { names: [], labels: [] };
    applyHighlight();
}

// ---- transitions that can be clicked ------------------------------------------------------

// What the pointer says about a transition: what it is and its weight now.
function describeTransition(name, node) {
    const weight = state.parameters?.transition_params?.transition_weights?.[name];
    const what = node.silent ? `${name} (silent)` : node.label;
    let value = '';
    if (typeof weight === 'number') value = ` — weight ${Number(weight.toFixed(3))}`;
    else if (weight && typeof weight === 'object') value = ' — weight from a decision tree';
    return `${what}${value}. Click to edit.`;
}

// Make each transition of the drawing something that can be pointed at,
// reached with Tab and activated.
function prepareTransitions(svg, nodes) {
    drawn.byName.clear();
    drawn.byLabel.clear();
    for (const [id, node] of Object.entries(nodes || {})) {
        if (node.type !== 'transition') continue;
        const element = svg.querySelector(`#${CSS.escape(id)}`);
        if (!element) continue;
        element.dataset.transition = node.name;
        element.setAttribute('tabindex', '0');
        element.setAttribute('role', 'button');
        element.setAttribute('aria-label', node.silent ? `Silent transition ${node.name}` : `Transition ${node.label}`);
        // Graphviz titles a node with its id: say what it is instead, and its
        // weight at the moment the pointer arrives (it changes while editing).
        const title = element.querySelector('title');
        const describe = () => { if (title) title.textContent = describeTransition(node.name, node); };
        describe();
        element.addEventListener('mouseenter', describe);
        element.addEventListener('focus', describe);

        drawn.byName.set(node.name, element);
        if (!node.silent) {
            if (!drawn.byLabel.has(node.label)) drawn.byLabel.set(node.label, []);
            drawn.byLabel.get(node.label).push(element);
        }
    }
}

function transitionOf(event) {
    const element = event.target instanceof Element ? event.target.closest('.pn-transition') : null;
    return element ? element.dataset.transition : null;
}

function bindContainer() {
    const container = document.getElementById('petriNetContainer');
    if (!container || container.dataset.bound) return;
    container.dataset.bound = '1';

    container.addEventListener('mousedown', (event) => {
        if (event.button !== 0) return;
        Object.assign(view, {
            dragging: true, moved: false,
            startX: event.clientX, startY: event.clientY, startTx: view.tx, startTy: view.ty,
        });
        container.style.cursor = 'grabbing';
        event.preventDefault();
    });
    window.addEventListener('mousemove', (event) => {
        if (!view.dragging) return;
        const dx = event.clientX - view.startX;
        const dy = event.clientY - view.startY;
        if (Math.abs(dx) > CLICK_TOLERANCE || Math.abs(dy) > CLICK_TOLERANCE) view.moved = true;
        if (!view.moved) return;
        view.tx = view.startTx + dx;
        view.ty = view.startTy + dy;
        applyTransform();
    });
    window.addEventListener('mouseup', () => {
        if (!view.dragging) return;
        view.dragging = false;
        container.style.cursor = 'grab';
    });

    // A click that was not the end of a drag opens the transition under it.
    container.addEventListener('click', (event) => {
        const name = transitionOf(event);
        if (name && !view.moved) onTransitionClick(name);
    });
    container.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const name = transitionOf(event);
        if (!name) return;
        event.preventDefault();
        onTransitionClick(name);
    });

    container.addEventListener('wheel', (event) => {
        event.preventDefault();
        const frame = container.getBoundingClientRect();
        zoomAt(view.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15), event.clientX - frame.left, event.clientY - frame.top);
    }, { passive: false });
}

// ---- drawing ---------------------------------------------------------------------------------

function showMessage(text) {
    const empty = document.getElementById('petriNetEmptyState');
    if (!empty) return;
    empty.style.display = text ? 'flex' : 'none';
    if (text) empty.querySelector('span').textContent = text;
}

function renderStats(processModel) {
    const statsEl = document.getElementById('petriNetStats');
    if (!statsEl) return;
    const count = (list) => (list ? list.length : 0);
    const metric = (value) => (value ? value.toFixed(2) : '0');
    const cell = (classes, name, value) => `
            <div class="col-md-4">
                <div class="${classes}">${name}</div>
                <div class="${classes}">${escapeHtml(value)}</div>
            </div>`;
    statsEl.innerHTML = `
        <div class="row text-center">${cell('text-muted', 'Activities', count(processModel.activities))}${cell('text-muted', 'Transitions', count(processModel.transitions))}${cell('text-muted', 'Places', count(processModel.places))}${cell('fw-bold text-success', 'Fitness', metric(processModel.fitness))}${cell('fw-bold text-warning', 'Precision', metric(processModel.precision))}${cell('fw-bold text-info', 'F-Measure', metric(processModel.f_measure))}
        </div>
    `;
}

/**
 * Show the net of `processModel`. A net that is already on screen is left as
 * it is, with its zoom and position: only the highlight is removed.
 */
export async function renderPetriNet(processModel) {
    const viewport = document.getElementById('petriNetViewport');
    const zoomGroup = document.getElementById('petriNetZoomGroup');
    const statsEl = document.getElementById('petriNetStats');
    if (!viewport) return;

    if (!processModel || !processModel.dot) {
        requested++;
        drawn.dot = null;
        drawn.byName.clear();
        drawn.byLabel.clear();
        wanted = { names: [], labels: [] };
        viewport.replaceChildren();
        if (zoomGroup) zoomGroup.style.display = 'none';
        if (statsEl) statsEl.innerHTML = '';
        showMessage(processModel ? 'No drawing available for this process model' : 'No process model data available');
        return;
    }

    renderStats(processModel);
    if (processModel.dot === drawn.dot && viewport.querySelector('svg')) {
        clearHighlight();
        return;
    }

    const request = ++requested;
    wanted = { names: [], labels: [] };     // what was asked for belonged to another net
    let svg;
    try {
        svg = await renderDot(processModel.dot);
    } catch (error) {
        if (request !== requested) return;
        console.error('The process model could not be drawn:', error);
        viewport.replaceChildren();
        drawn.dot = null;
        showMessage('The process model could not be drawn');
        return;
    }
    if (request !== requested) return;

    const frame = document.createElement('div');
    frame.className = 'petri-net-frame';
    svg.style.display = 'block';
    frame.appendChild(svg);
    viewport.replaceChildren(frame);
    showMessage('');
    if (zoomGroup) zoomGroup.style.display = 'flex';

    prepareTransitions(svg, processModel.nodes);
    drawn.dot = processModel.dot;
    bindContainer();

    // Fit the drawing at once, so that it does not flash at full size in a
    // corner, and again at the next frame: when the card has just been shown
    // its width is not known yet.
    view.naturalW = frame.offsetWidth || 800;
    view.naturalH = frame.offsetHeight || 500;
    fitView();
    requestAnimationFrame(() => {
        view.naturalW = frame.offsetWidth || view.naturalW;
        view.naturalH = frame.offsetHeight || view.naturalH;
        fitView();
        applyHighlight();
    });
}

on('click', {
    'petri-zoom-by': (element) => setZoom(view.scale + parseFloat(element.dataset.step)),
    'petri-fit': () => fitView(),
    'clear-petri-highlight': () => clearHighlight(),
});
on('input', { 'petri-zoom': (element) => setZoom(element.value) });
