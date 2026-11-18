/**
 * Parameters tab "Waiting Times": how long a resource lets work wait, as a
 * distribution or (with decision rules) a tree of distributions.
 */

import { escapeHtml, on } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';
import { highlightTransitionVisualization, revertToOriginalVisualization } from '../petri-net.js';
import { registerDistributionKind, renderDistributionParameters, renderFamilySelect } from './distribution-editor.js';
import { editTimeDistribution } from './distributions.js';
import { returnActivitiesPerResource } from './resource-matrix.js';
import { renderDecisionTreeDistributionEditor } from './tree-editor.js';
import { isDecisionTreeModeForWaitingTimes, isTree, singleLeafTimeTree } from './trees.js';

const PICK_A_RESOURCE = '<p class="text-muted">Select a resource to edit its waiting time parameters</p>';

export function renderWaitingTimeParameters() {
    const container = document.getElementById('waitingParams');
    // Every resource is listed, also the ones without a waiting time yet.
    const allResources = state.parameters.resource_params?.resources || [];

    let html = '<div class="mb-3">';
    html += '<h6 class="mb-3">Resource Waiting Times</h6>';
    html += '<label class="form-label">Select Resource:</label>';
    html += '<select class="form-select mb-3" id="resourceWaitingSelect" data-action="show-resource-waiting">';
    html += '<option value="">Choose a resource...</option>';
    allResources.forEach(resource => {
        html += `<option value="${escapeHtml(resource)}">${escapeHtml(resource)}</option>`;
    });
    html += '</select>';
    html += '<div id="resourceWaitingDisplay" class="border rounded p-3">';
    html += allResources.length === 0 ? '<p class="text-muted">No resources available</p>' : PICK_A_RESOURCE;
    html += '</div></div>';

    container.innerHTML = html;
}

/** Show the editor of one resource and highlight its activities in the drawing. */
export function showResourceWaiting(resourceName) {
    revertToOriginalVisualization();

    const display = document.getElementById('resourceWaitingDisplay');
    if (!resourceName) {
        display.innerHTML = PICK_A_RESOURCE;
        return;
    }

    highlightTransitionVisualization(returnActivitiesPerResource(resourceName));

    if (!state.parameters.waiting_time_params.resource_waiting_times) {
        state.parameters.waiting_time_params.resource_waiting_times = {};
    }
    const waitingTimes = state.parameters.waiting_time_params.resource_waiting_times;
    // A resource without a waiting time gets one to start from, of the same
    // kind as the others: a tree when the session uses decision rules.
    if (!waitingTimes[resourceName]) {
        waitingTimes[resourceName] = isDecisionTreeModeForWaitingTimes()
            ? singleLeafTimeTree()
            : { distribution: 'expon', parameters: { mean: 15 } };
    }
    const params = waitingTimes[resourceName];

    if (isTree(params)) {
        display.innerHTML = `<h6 class="mb-3">${escapeHtml(resourceName)} Decision Tree</h6><div class="small"></div>`;
        renderDecisionTreeDistributionEditor(params, display.querySelector('div'), 'waiting');
    } else {
        const distribution = params.distribution || 'norm';
        display.innerHTML = `
            <h6 class="mb-3">${escapeHtml(resourceName)} Waiting Time</h6>
            <div class="row">
                <div class="col-md-6">
                    <label class="form-label small">Distribution</label>
                    ${renderFamilySelect('waiting', resourceName, distribution)}
                </div>
                <div class="col-md-6">
                    ${renderDistributionParameters('waiting', resourceName, distribution, params.parameters || params)}
                </div>
            </div>
        `;
    }
}

function updateWaitingParam(resource, param, value) {
    markParametersDirty();
    if (!state.parameters.waiting_time_params.resource_waiting_times) {
        state.parameters.waiting_time_params.resource_waiting_times = {};
    }
    const waitingTimes = state.parameters.waiting_time_params.resource_waiting_times;
    if (!waitingTimes[resource]) waitingTimes[resource] = {};
    editTimeDistribution(waitingTimes[resource], param, value);
}

registerDistributionKind('waiting', { update: updateWaitingParam, refresh: showResourceWaiting });

on('change', { 'show-resource-waiting': (element) => showResourceWaiting(element.value) });
