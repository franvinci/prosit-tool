/**
 * Parameters tab "Transitions": the weight of each transition of the Petri
 * net, a number or (with decision rules) a tree.
 */

import { escapeHtml, infoIcon, initTooltipsIn, on } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';
import { highlightTransitionVisualization, revertToOriginalVisualization } from '../petri-net.js';
import { renderDecisionTreeEditor } from './tree-editor.js';

const WEIGHT_HELP = 'Represents the probability of firing a transition when it is enabled.';

function transitionLabels() {
    return (state.parameters && state.parameters.process_model && state.parameters.process_model.transition_label_map) || {};
}

export function renderTransitionParameters(transitionParams) {
    const container = document.getElementById('transitionParams');
    const weights = transitionParams.transition_weights || {};
    const transitions = Object.keys(weights);
    const labelMap = transitionLabels();

    let html = '<div class="mb-3">';
    html += `<h6 class="mb-3">Transition Weights ${infoIcon(WEIGHT_HELP)}</h6>`;
    html += '<label class="form-label">Select Transition:</label>';
    html += '<select class="form-select mb-3" id="transitionSelect" data-action="show-transition">';
    html += '<option value="">Choose a transition...</option>';

    const haveLabelMap = Object.keys(labelMap).length > 0;
    transitions.forEach(transition => {
        const mapped = labelMap[transition];
        const display = mapped || transition;
        // A transition whose label equals its name has no label of its own.
        const suffix = (haveLabelMap && mapped === transition) ? ' (silent)' : '';
        html += `<option value="${escapeHtml(transition)}">${escapeHtml(display + suffix)}</option>`;
    });

    html += '</select>';
    html += '<div id="transitionWeightDisplay" class="border rounded p-3">';
    html += transitions.length === 0
        ? '<p class="text-muted">No transitions available</p>'
        : '<p class="text-muted">Select a transition to edit its weight</p>';
    html += '</div></div>';

    container.innerHTML = html;
    initTooltipsIn(container);
}

/** Show the editor of one transition and highlight it in the drawing. */
export function showTransitionWeights(transitionName) {
    revertToOriginalVisualization();

    const display = document.getElementById('transitionWeightDisplay');
    if (!transitionName || !state.parameters.transition_params.transition_weights[transitionName]) {
        display.innerHTML = '<p class="text-muted">No weight data available</p>';
        return;
    }

    highlightTransitionVisualization(transitionName);

    const weight = state.parameters.transition_params.transition_weights[transitionName];
    const displayName = transitionLabels()[transitionName] || transitionName;

    if (typeof weight === 'number') {
        // A plain weight: a slider and a number field showing the same value.
        const name = escapeHtml(transitionName);
        display.innerHTML = `
        <h6 class="mb-3">${escapeHtml(displayName)} Weight</h6>
        <div class="mb-3">
            <label class="form-label">Weight Value: <span id="transitionWeightValue">${weight}</span></label>
            <div class="input-group">
                <input type="range" class="form-range me-3" min="0" max="1" step="0.01"
                       value="${weight}" data-action="set-transition-weight" data-transition="${name}">
                <input type="number" class="form-control" id="transitionWeightNumber" style="width: 100px;" min="0" max="1" step="0.01"
                       value="${weight}" data-action="set-transition-weight" data-transition="${name}">
            </div>
        </div>`;
    } else {
        // Decision rules: the weight depends on the case, through a tree.
        display.innerHTML = `<h6 class="mb-3">${escapeHtml(displayName)} Decision Tree</h6><div class="small"></div>`;
        renderDecisionTreeEditor(weight, display.querySelector('div'));
    }
}

function updateTransitionWeight(transition, value) {
    if (!state.parameters.transition_params.transition_weights) {
        state.parameters.transition_params.transition_weights = {};
    }
    state.parameters.transition_params.transition_weights[transition] = parseFloat(value);
    markParametersDirty();

    // The slider, the number field and the label show the same weight.
    const display = document.getElementById('transitionWeightDisplay');
    display.querySelectorAll('[data-action="set-transition-weight"]').forEach(input => {
        if (input.value !== value) input.value = value;
    });
    const label = document.getElementById('transitionWeightValue');
    if (label) label.textContent = value;
}

on('change', {
    'show-transition': (element) => showTransitionWeights(element.value),
    'set-transition-weight': (element) => updateTransitionWeight(element.dataset.transition, element.value),
});
