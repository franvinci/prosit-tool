/**
 * The drawing of the Petri net: showing it, panning and zooming it, and
 * highlighting the transitions an editor is about.
 */

import { escapeHtml, on } from '../core/dom.js';
import { state } from '../core/state.js';

/** Colour the given transitions (one name or a list) in the drawing. */
export function highlightTransitionVisualization(transitionNames, newColor="#c77dff") {

    // Store original visualization if not already stored
    if (!state.originalVisualization && state.parameters?.process_model?.visualization) {
        state.originalVisualization = state.parameters.process_model.visualization;
    }

    // Ensure transitionNames is an array
    if (!Array.isArray(transitionNames)) {
        transitionNames = [transitionNames];
    }

    // Loop through each transition name in the array
    transitionNames.forEach(transitionName => {
        const transitionId = state.parameters.process_model.map_transitionName_to_id[transitionName];

        // Use a more specific regex to avoid issues with other attributes
        const regex = new RegExp(`(<title>${transitionId}<\\/title>\\s*<(ellipse|polygon) fill=)"([^"]*)"`, "m");

        // Check if the pattern exists and then replace the color
        if (regex.test(state.parameters.process_model.visualization)) {
            // The `replace` method is chained to ensure each transition is updated
            state.parameters.process_model.visualization = state.parameters.process_model.visualization.replace(regex, `$1"${newColor}"`);
        }
    });

    // Render the Petri net only once after all changes are made
    renderPetriNet(state.parameters.process_model);
}

/** Show the drawing again without any highlight. */
export function revertToOriginalVisualization() {
    if (state.originalVisualization && state.parameters?.process_model) {
        state.parameters.process_model.visualization = state.originalVisualization;
        renderPetriNet(state.parameters.process_model);
    }
}

// Pan + zoom state for the discovered process model. The SVG is held in a
// viewport `<div>` inside a fixed-height container; transform translates +
// scales it, while the container clips overflow so the model never bleeds into
// the layout below.
const _petriPan = {
    scale: 1, tx: 0, ty: 0,
    dragging: false, startX: 0, startY: 0, startTx: 0, startTy: 0,
    naturalW: 0, naturalH: 0,
};

function _applyPetriTransform() {
    const v = document.getElementById('petriNetViewport');
    if (!v) return;
    v.style.transform = `translate(${_petriPan.tx}px, ${_petriPan.ty}px) scale(${_petriPan.scale})`;
    const slider = document.getElementById('petriNetZoom');
    if (slider) slider.value = _petriPan.scale;
}

function setPetriNetZoom(value) {
    const target = Math.max(0.3, Math.min(5, parseFloat(value) || 1));
    const c = document.getElementById('petriNetContainer');
    if (!c) { _petriPan.scale = target; _applyPetriTransform(); return; }
    // Zoom toward the centre of the viewport, keeping that point fixed.
    const cx = c.clientWidth / 2;
    const cy = c.clientHeight / 2;
    _petriPan.tx = cx - (cx - _petriPan.tx) * (target / _petriPan.scale);
    _petriPan.ty = cy - (cy - _petriPan.ty) * (target / _petriPan.scale);
    _petriPan.scale = target;
    _applyPetriTransform();
}

function petriNetZoomBy(delta) {
    setPetriNetZoom(_petriPan.scale + delta);
}

// Resize the container so its height matches the SVG's aspect ratio at the
// current container width. Clamped to keep tiny / huge graphs sensible.
function _autoSizePetriContainer() {
    const c = document.getElementById('petriNetContainer');
    if (!c) return;
    const w = _petriPan.naturalW, h = _petriPan.naturalH;
    if (!w || !h) return;
    const cw = c.clientWidth;
    if (!cw) return;
    const aspectH = cw * (h / w);
    const target = Math.max(160, Math.min(500, aspectH + 20));
    c.style.height = target + 'px';
}

function resetPetriNetView() {
    const c = document.getElementById('petriNetContainer');
    const v = document.getElementById('petriNetViewport');
    if (!c || !v) return;
    _autoSizePetriContainer();
    const w = _petriPan.naturalW || v.scrollWidth || 800;
    const h = _petriPan.naturalH || v.scrollHeight || 500;
    if (w <= 0 || h <= 0) {
        _petriPan.scale = 1; _petriPan.tx = 0; _petriPan.ty = 0;
        _applyPetriTransform();
        return;
    }
    const padding = 16;
    const fitScale = Math.min(
        (c.clientWidth - padding * 2) / w,
        (c.clientHeight - padding * 2) / h,
        1
    );
    _petriPan.scale = Math.max(0.3, fitScale);
    _petriPan.tx = (c.clientWidth - w * _petriPan.scale) / 2;
    _petriPan.ty = (c.clientHeight - h * _petriPan.scale) / 2;
    _applyPetriTransform();
}

function _bindPetriPanHandlers() {
    const c = document.getElementById('petriNetContainer');
    if (!c || c.dataset.panBound) return;
    c.dataset.panBound = '1';

    c.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        _petriPan.dragging = true;
        _petriPan.startX = e.clientX;
        _petriPan.startY = e.clientY;
        _petriPan.startTx = _petriPan.tx;
        _petriPan.startTy = _petriPan.ty;
        c.style.cursor = 'grabbing';
        e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
        if (!_petriPan.dragging) return;
        _petriPan.tx = _petriPan.startTx + (e.clientX - _petriPan.startX);
        _petriPan.ty = _petriPan.startTy + (e.clientY - _petriPan.startY);
        _applyPetriTransform();
    });
    const endDrag = () => {
        if (!_petriPan.dragging) return;
        _petriPan.dragging = false;
        c.style.cursor = 'grab';
    };
    window.addEventListener('mouseup', endDrag);
    c.addEventListener('mouseleave', () => { /* keep dragging on window mouseup */ });

    c.addEventListener('wheel', (e) => {
        e.preventDefault();
        const rect = c.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        const newScale = Math.max(0.3, Math.min(5, _petriPan.scale * factor));
        _petriPan.tx = mx - (mx - _petriPan.tx) * (newScale / _petriPan.scale);
        _petriPan.ty = my - (my - _petriPan.ty) * (newScale / _petriPan.scale);
        _petriPan.scale = newScale;
        _applyPetriTransform();
    }, { passive: false });
}

/** Show the drawing of the net (or what is known of it) and fit it in its box. */
export function renderPetriNet(processModel) {
    const viewport = document.getElementById('petriNetViewport');
    const empty = document.getElementById('petriNetEmptyState');
    const zoomGroup = document.getElementById('petriNetZoomGroup');
    const statsEl = document.getElementById('petriNetStats');

    if (zoomGroup) zoomGroup.style.display = 'none';
    if (statsEl) statsEl.innerHTML = '';

    // Reset state
    _petriPan.scale = 1; _petriPan.tx = 0; _petriPan.ty = 0;
    _petriPan.dragging = false;
    _petriPan.naturalW = 0; _petriPan.naturalH = 0;

    if (viewport) viewport.innerHTML = '';
    if (empty) empty.style.display = 'flex';

    if (!processModel) return;

    if (processModel.visualization) {
        if (processModel.visualization.includes('<svg')) {
            // Keep graphviz's native width/height (in pt) so the SVG has a
            // measurable size; we just present it in our own wrap.
            const wrap = document.createElement('div');
            wrap.style.background = 'white';
            wrap.style.borderRadius = '8px';
            wrap.style.padding = '10px';
            wrap.style.border = '1px solid #dee2e6';
            wrap.style.display = 'inline-block';
            wrap.innerHTML = processModel.visualization;
            const svg = wrap.querySelector('svg');
            if (svg) svg.style.display = 'block';
            if (viewport) viewport.appendChild(wrap);
            if (empty) empty.style.display = 'none';
            if (zoomGroup) zoomGroup.style.display = 'flex';
            _bindPetriPanHandlers();

            // Read the wrap's natural size (forces layout) and fit it
            // synchronously so the SVG appears centred + scaled on the first
            // paint instead of flashing at top-left at full size.
            _petriPan.naturalW = wrap.offsetWidth || 800;
            _petriPan.naturalH = wrap.offsetHeight || 500;
            resetPetriNetView();
            // Re-fit once on next frame in case the container's clientWidth
            // wasn't yet computed at the time of this render (e.g. after a
            // display: none → block transition).
            requestAnimationFrame(() => resetPetriNetView());

            _renderPetriNetStats(processModel);
        } else {
            // Base64 image fallback (rarely used).
            if (viewport) {
                viewport.innerHTML = `<img src="${escapeHtml(processModel.visualization)}" alt="Petri Net" style="max-width: 100%; max-height: 100%;">`;
            }
            if (empty) empty.style.display = 'none';
            _renderPetriNetStats(processModel);
        }
        return;
    }

    const activities = processModel.activities || [];
    if (empty) {
        empty.style.display = 'flex';
        empty.querySelector('span').textContent = activities.length
            ? 'Visualization not available — see activity list below'
            : 'No process model data available';
    }
    if (activities.length && viewport) {
        const list = document.createElement('div');
        list.style.padding = '12px';
        let html = '<div class="row">';
        activities.forEach((a, i) => {
            html += `<div class="col-md-6 mb-2"><span class="badge bg-primary me-2">${i + 1}</span>${escapeHtml(a)}</div>`;
        });
        html += '</div>';
        list.innerHTML = html;
        viewport.appendChild(list);
    }
}

function _renderPetriNetStats(processModel) {
    const statsEl = document.getElementById('petriNetStats');
    if (!statsEl) return;
    const fitness = processModel.fitness ? processModel.fitness.toFixed(2) : '0';
    const precision = processModel.precision ? processModel.precision.toFixed(2) : '0';
    const fmeasure = processModel.f_measure ? processModel.f_measure.toFixed(2) : '0';
    statsEl.innerHTML = `
        <div class="row text-center">
            <div class="col-md-4">
                <div class="text-muted">Activities</div>
                <div class="text-muted">${processModel.activities ? processModel.activities.length : 0}</div>
            </div>
            <div class="col-md-4">
                <div class="text-muted">Transitions</div>
                <div class="text-muted">${processModel.transitions ? processModel.transitions.length : 0}</div>
            </div>
            <div class="col-md-4">
                <div class="text-muted">Places</div>
                <div class="text-muted">${processModel.places ? processModel.places.length : 0}</div>
            </div>
            <div class="col-md-4">
                <div class="fw-bold text-success">Fitness</div>
                <div class="fw-bold text-success">${fitness}</div>
            </div>
            <div class="col-md-4">
                <div class="fw-bold text-warning">Precision</div>
                <div class="fw-bold text-warning">${precision}</div>
            </div>
            <div class="col-md-4">
                <div class="fw-bold text-info">F-Measure</div>
                <div class="fw-bold text-info">${fmeasure}</div>
            </div>
        </div>
    `;
}

on('click', {
    'petri-zoom-by': (element) => petriNetZoomBy(parseFloat(element.dataset.step)),
    'petri-fit': () => resetPetriNetView(),
    'clear-petri-highlight': () => revertToOriginalVisualization(),
});
on('input', { 'petri-zoom': (element) => setPetriNetZoom(element.value) });
