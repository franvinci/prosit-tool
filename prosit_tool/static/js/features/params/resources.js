/**
 * Parameters tab "Resources": the weight of each resource (a number or, with
 * decision rules, a tree), and adding or removing a resource together with
 * everything that refers to it.
 */

import { escapeHtml, infoIcon, initTooltipsIn, on } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';
import { clearHighlight, highlightActivities } from '../petri-net.js';
import { createDefaultWorkingHours, renderResourceCalendars } from './calendars.js';
import { attachMatrixHandlers, renderResourceActivityMatrix, returnActivitiesPerResource } from './resource-matrix.js';
import { renderDecisionTreeEditor } from './tree-editor.js';
import { isDecisionTreeModeForResourceWeights, isDecisionTreeModeForWaitingTimes, singleLeafTimeTree } from './trees.js';
import { renderWaitingTimeParameters } from './waiting.js';

const WEIGHT_HELP = 'Represents the probability of choosing a resource whenever it is available, either free or multitasking.';

export function renderResourceParameters(resourceParams) {
    const container = document.getElementById('resourceParams');
    const activityContainer = document.getElementById('activityResourceParams');
    const calendarContainer = document.getElementById('resourceCalendars');

    const resources = resourceParams.resources || [];
    const maxConcurrency = resourceParams.max_concurrency || {};
    const actToResources = resourceParams.act_to_resources || {};
    const activityNames = Object.keys(actToResources);

    // Weights: a select of the resources and the editor of the chosen one.
    let html = '<div class="mb-12">';
    html += '<div class="d-flex justify-content-between align-items-center mb-2">';
    html += '<button class="btn btn-outline-success btn-sm" data-action="add-resource">';
    html += '<i data-feather="plus" class="me-1"></i>Add Resource</button>';
    html += '</div>';

    html += '<div class="card">';
    html += `<div class="card-header py-2"><h6 class="mb-0">Resource Weights ${infoIcon(WEIGHT_HELP)}</h6></div>`;
    html += '<div class="card-body">';
    html += '<label class="form-label">Select Resource:</label>';
    html += '<select class="form-select mb-3" id="resourceWeightSelect" data-action="show-resource-weight">';
    html += '<option value="">Choose a resource...</option>';
    resources.forEach(resource => {
        html += `<option value="${escapeHtml(resource)}">${escapeHtml(resource)}</option>`;
    });
    html += '</select>';
    html += '<div id="resourceWeightDisplay" class="border rounded p-3">';
    html += resources.length
        ? '<p class="text-muted">Select a resource to edit its weight</p>'
        : '<p class="text-muted">No resources available</p>';
    html += '</div></div>';
    html += '</div>';
    html += '</div>';

    container.innerHTML = html;

    // Who performs what, and how many cases each resource handles at once.
    activityContainer.innerHTML = renderResourceActivityMatrix(resources, activityNames, actToResources, maxConcurrency);
    attachMatrixHandlers(activityContainer);

    calendarContainer.innerHTML = '<div class="card"><div class="card-header py-2"><h6 class="mb-0">Resource Calendars</h6></div><div class="card-body"></div></div>';
    renderResourceCalendars(resourceParams.calendars || {}, calendarContainer.querySelector('.card-body'));

    initTooltipsIn(container);
}

/** Show the editor of one resource and highlight its activities in the drawing. */
export function showResourceWeight(resourceName) {
    clearHighlight();

    const display = document.getElementById('resourceWeightDisplay');
    if (!resourceName) {
        display.innerHTML = '<p class="text-muted">Select a resource to edit its weight</p>';
        return;
    }

    highlightActivities(returnActivitiesPerResource(resourceName));

    // A weight of zero is a weight too: only a missing one gets the default.
    const weight = state.parameters.resource_params.resource_weights?.[resourceName] ?? 0.1;
    const name = escapeHtml(resourceName);

    if (typeof weight === 'number') {
        display.innerHTML = `
        <h6 class="mb-3">${name} Weight</h6>
        <div class="d-flex justify-content-between align-items-center mb-2">
            <span>Weight Value: <span id="resourceWeightValue">${weight}</span></span>
            <button class="btn btn-outline-danger btn-sm" data-action="remove-resource" data-resource="${name}" title="Remove resource">
                <i data-feather="x" class="me-1"></i>Remove Resource
            </button>
        </div>
        <div class="mb-3">
            <div class="d-flex align-items-center gap-2">
                <input type="range" class="form-range flex-grow-1" min="0" max="1" step="0.01"
                       value="${weight}" data-action="set-resource-weight" data-resource="${name}">
                <input type="number" class="form-control" id="resourceWeightNumber" style="width: 100px;"
                       min="0" max="1" step="0.01" value="${weight}"
                       data-action="set-resource-weight" data-resource="${name}">
            </div>
        </div>`;
    } else {
        display.innerHTML = `<h6 class="mb-3">${name} Decision Tree</h6><div class="small"></div>`;
        renderDecisionTreeEditor(weight, display.querySelector('div'), 'resource');
    }
    feather.replace();
}

function updateResourceWeight(resource, value) {
    if (!state.parameters.resource_params.resource_weights) {
        state.parameters.resource_params.resource_weights = {};
    }
    state.parameters.resource_params.resource_weights[resource] = parseFloat(value);
    markParametersDirty();

    // The slider, the number field and the label show the same weight.
    const display = document.getElementById('resourceWeightDisplay');
    display.querySelectorAll('[data-action="set-resource-weight"]').forEach(input => {
        if (input.value !== value) input.value = value;
    });
    const label = document.getElementById('resourceWeightValue');
    if (label) label.textContent = value;
}

function showAddResourceModal() {
    const modalHtml = `
        <div class="modal fade" id="addResourceModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Add New Resource</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label for="newResourceName" class="form-label">Resource Name</label>
                            <input type="text" class="form-control" id="newResourceName"
                                   placeholder="Enter resource name">
                        </div>
                        <div class="mb-3" id="newResourceWeightGroup">
                            <label for="newResourceWeight" class="form-label">Resource Weight</label>
                            <input type="number" class="form-control" id="newResourceWeight"
                                   min="0" max="1" step="0.01" value="0.1">
                        </div>
                        <div class="mb-3" id="copyFromResourceGroup" style="display:none;">
                            <label for="copyFromResourceSelect" class="form-label">Copy From Existing Resource</label>
                            <select class="form-select" id="copyFromResourceSelect">
                                <option value="">Select a resource</option>
                            </select>
                            <div class="form-text">Copies weight, waiting time, calendar, max concurrency, and activity assignments.</div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-success" data-action="confirm-add-resource">Add Resource</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if any
    const existingModal = document.getElementById('addResourceModal');
    if (existingModal) {
        existingModal.remove();
    }

    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('addResourceModal'));
    modal.show();

    // With decision rules a new resource is a copy of an existing one: a tree
    // cannot be typed in a field the way a weight can.
    if (isDecisionTreeModeForResourceWeights() || isDecisionTreeModeForWaitingTimes()) {
        document.getElementById('copyFromResourceGroup').style.display = 'block';
        const copySelect = document.getElementById('copyFromResourceSelect');
        const resources = state.parameters?.resource_params?.resources || [];
        resources.forEach(resource => copySelect.appendChild(new Option(resource, resource)));
        if (isDecisionTreeModeForResourceWeights()) {
            document.getElementById('newResourceWeightGroup').style.display = 'none';
        }
    }
}

function addNewResource() {
    const resourceName = document.getElementById('newResourceName').value.trim();
    const weightInputEl = document.getElementById('newResourceWeight');
    const resourceWeight = weightInputEl && weightInputEl.offsetParent !== null ? parseFloat(weightInputEl.value) : null;
    const copyFrom = (document.getElementById('copyFromResourceSelect') && document.getElementById('copyFromResourceSelect').value) || '';

    if (!resourceName) {
        alert('Please enter a resource name');
        return;
    }

    if (state.parameters.resource_params.resources.includes(resourceName)) {
        alert('Resource already exists');
        return;
    }
    // Everything is checked before anything is added: a resource added
    // halfway would stay in the list with no weight.
    const weights = state.parameters.resource_params.resource_weights || {};
    if (isDecisionTreeModeForResourceWeights() && !(copyFrom && weights[copyFrom] !== undefined)) {
        alert('Please choose a resource to copy the decision tree from.');
        return;
    }

    state.parameters.resource_params.resources.push(resourceName);

    // "Copy from" copies everything the source has: weight, concurrency,
    // calendar, activities and waiting time.
    const rp = state.parameters.resource_params;

    // Resource weight
    if (!rp.resource_weights) rp.resource_weights = {};
    if (copyFrom && rp.resource_weights[copyFrom] !== undefined) {
        rp.resource_weights[resourceName] = deepClone(rp.resource_weights[copyFrom]);
    } else {
        rp.resource_weights[resourceName] = (typeof resourceWeight === 'number' && !isNaN(resourceWeight)) ? resourceWeight : 0.1;
    }

    // Max concurrency — copied from source when provided, else default 1.
    if (!rp.max_concurrency) rp.max_concurrency = {};
    if (copyFrom && rp.max_concurrency[copyFrom] !== undefined) {
        rp.max_concurrency[resourceName] = rp.max_concurrency[copyFrom];
    } else {
        rp.max_concurrency[resourceName] = 1;
    }

    // Calendar
    if (!rp.calendars) rp.calendars = {};
    if (copyFrom && rp.calendars[copyFrom]) {
        rp.calendars[resourceName] = deepClone(rp.calendars[copyFrom]);
    } else {
        rp.calendars[resourceName] = {
            'Monday': createDefaultWorkingHours(),
            'Tuesday': createDefaultWorkingHours(),
            'Wednesday': createDefaultWorkingHours(),
            'Thursday': createDefaultWorkingHours(),
            'Friday': createDefaultWorkingHours(),
            'Saturday': {},
            'Sunday': {}
        };
    }

    // Activities: the ones of the source when copying, otherwise all of them.
    if (rp.act_to_resources) {
        Object.keys(rp.act_to_resources).forEach(activity => {
            const list = rp.act_to_resources[activity];
            if (!Array.isArray(list)) return;
            const sourceAssigned = copyFrom ? list.includes(copyFrom) : true;
            if (sourceAssigned && !list.includes(resourceName)) {
                list.push(resourceName);
            }
        });
    }

    // Waiting time
    if (!state.parameters.waiting_time_params) {
        state.parameters.waiting_time_params = {};
    }
    if (!state.parameters.waiting_time_params.resource_waiting_times) {
        state.parameters.waiting_time_params.resource_waiting_times = {};
    }
    const wt = state.parameters.waiting_time_params.resource_waiting_times;
    if (isDecisionTreeModeForWaitingTimes()) {
        if (copyFrom && wt[copyFrom] !== undefined) {
            wt[resourceName] = deepClone(wt[copyFrom]);
        } else {
            wt[resourceName] = singleLeafTimeTree();
        }
    } else if (copyFrom && wt[copyFrom] !== undefined) {
        wt[resourceName] = deepClone(wt[copyFrom]);
    } else {
        wt[resourceName] = { distribution: 'expon', parameters: { mean: 15 } };
    }

    markParametersDirty();

    // Refresh the UI
    renderResourceParameters(state.parameters.resource_params);
    renderWaitingTimeParameters();

    // Close modal
    const modal = bootstrap.Modal.getInstance(document.getElementById('addResourceModal'));
    modal.hide();

    feather.replace();
}

function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

function removeResource(resourceName) {
    if (!confirm(`Are you sure you want to remove resource "${resourceName}"?`)) {
        return;
    }

    // Remove from resources list
    const index = state.parameters.resource_params.resources.indexOf(resourceName);
    if (index > -1) {
        state.parameters.resource_params.resources.splice(index, 1);
    }

    // Remove resource weight
    if (state.parameters.resource_params.resource_weights) {
        delete state.parameters.resource_params.resource_weights[resourceName];
    }

    // Remove max concurrency entry
    if (state.parameters.resource_params.max_concurrency) {
        delete state.parameters.resource_params.max_concurrency[resourceName];
    }

    // Remove calendar
    if (state.parameters.resource_params.calendars) {
        delete state.parameters.resource_params.calendars[resourceName];
    }

    // Remove from activity assignments
    if (state.parameters.resource_params.act_to_resources) {
        Object.keys(state.parameters.resource_params.act_to_resources).forEach(activity => {
            const resIndex = state.parameters.resource_params.act_to_resources[activity].indexOf(resourceName);
            if (resIndex > -1) {
                state.parameters.resource_params.act_to_resources[activity].splice(resIndex, 1);
            }
        });
    }

    // Remove waiting time parameters
    if (state.parameters.waiting_time_params && state.parameters.waiting_time_params.resource_waiting_times) {
        delete state.parameters.waiting_time_params.resource_waiting_times[resourceName];
    }
    markParametersDirty();

    // Refresh the UI
    renderResourceParameters(state.parameters.resource_params);
    renderWaitingTimeParameters();

    feather.replace();
}

on('change', {
    'show-resource-weight': (element) => showResourceWeight(element.value),
    'set-resource-weight': (element) => updateResourceWeight(element.dataset.resource, element.value),
});
on('click', {
    'add-resource': () => showAddResourceModal(),
    'confirm-add-resource': () => addNewResource(),
    'remove-resource': (element) => removeResource(element.dataset.resource),
});
