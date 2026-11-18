/**
 * Parameters tab "Execution Times": how long each activity takes, as a
 * distribution or (with decision rules) a tree of distributions.
 */

import { escapeHtml, on } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';
import { highlightTransitionVisualization, revertToOriginalVisualization } from '../petri-net.js';
import { registerDistributionKind, renderDistributionParameters, renderFamilySelect } from './distribution-editor.js';
import { editTimeDistribution } from './distributions.js';
import { renderDecisionTreeDistributionEditor } from './tree-editor.js';
import { isTree } from './trees.js';

export function renderExecutionTimeParameters(executionParams) {
    const container = document.getElementById('executionParams');
    const durations = executionParams.activity_durations || {};
    const activities = Object.keys(durations);

    let html = '<div class="mb-3">';
    html += '<h6 class="mb-3">Activity Duration Distributions</h6>';
    html += '<label class="form-label">Select Activity:</label>';
    html += '<select class="form-select mb-3" id="activityExecutionSelect" data-action="show-activity-execution">';
    html += '<option value="">Choose an activity...</option>';
    activities.forEach(activity => {
        html += `<option value="${escapeHtml(activity)}">${escapeHtml(activity)}</option>`;
    });
    html += '</select>';
    html += '<div id="activityExecutionDisplay" class="border rounded p-3">';
    html += activities.length === 0
        ? '<p class="text-muted">No activities available</p>'
        : '<p class="text-muted">Select an activity to edit its execution time parameters</p>';
    html += '</div></div>';

    container.innerHTML = html;
}

/** Show the editor of one activity and highlight it in the drawing. */
export function showActivityExecution(activityName) {
    revertToOriginalVisualization();

    const display = document.getElementById('activityExecutionDisplay');
    if (!activityName || !state.parameters.execution_time_params.activity_durations[activityName]) {
        display.innerHTML = '<p class="text-muted">No execution time data available</p>';
        return;
    }

    highlightTransitionVisualization(activityName);

    const params = state.parameters.execution_time_params.activity_durations[activityName];
    if (isTree(params)) {
        display.innerHTML = `<h6 class="mb-3">${escapeHtml(activityName)} Decision Tree</h6><div class="small"></div>`;
        renderDecisionTreeDistributionEditor(params, display.querySelector('div'), 'execution');
    } else {
        const distribution = (params && params.distribution) || 'norm';
        display.innerHTML = `
            <h6 class="mb-3">${escapeHtml(activityName)} Execution Time</h6>
            <div class="row">
                <div class="col-md-6">
                    <label class="form-label small">Distribution</label>
                    ${renderFamilySelect('execution', activityName, distribution)}
                </div>
                <div class="col-md-6">
                    ${renderDistributionParameters('execution', activityName, distribution, (params && (params.parameters || params)) || {})}
                </div>
            </div>
        `;
    }
}

function updateExecutionParam(activity, param, value) {
    markParametersDirty();
    const durations = state.parameters.execution_time_params.activity_durations;
    if (!durations[activity]) durations[activity] = {};
    editTimeDistribution(durations[activity], param, value);
}

registerDistributionKind('execution', { update: updateExecutionParam, refresh: showActivityExecution });

on('change', { 'show-activity-execution': (element) => showActivityExecution(element.value) });
