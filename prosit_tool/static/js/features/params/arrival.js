/**
 * Parameters tab "Arrival Times": how much time passes between one new case
 * and the next (a distribution or, with decision rules, a tree), and the
 * calendar of the hours in which cases can arrive.
 */

import { markParametersDirty, state } from '../../core/state.js';
import { renderArrivalCalendar } from './calendars.js';
import { registerDistributionKind, renderDistributionParameters, renderFamilySelect } from './distribution-editor.js';
import { editTimeDistribution } from './distributions.js';
import { renderDecisionTreeDistributionEditor } from './tree-editor.js';
import { isTree } from './trees.js';

// The arrival time is a single entry: the editor needs a name for it only to
// say which of its entries an edit belongs to.
const ARRIVAL = 'inter_arrival_time';

export function renderInterArrivalTimeParameters(arrivalParams) {
    const container = document.getElementById('arrivalParams');
    // Normally the entry is under `inter_arrival_time`; a tree may also come
    // as the parameters themselves.
    const candidate = arrivalParams && typeof arrivalParams === 'object' ? arrivalParams : {};
    const interArrival = isTree(candidate) ? candidate : (candidate.inter_arrival_time || {});
    const treeMode = isTree(interArrival.distribution);

    let html = '<div class="row">';

    html += '<div class="mb-12">';
    html += '<div class="card">';
    html += '<div class="card-header py-2">';
    html += '<h6 class="mb-0">Inter-Arrival Time Distribution</h6>';
    html += '</div>';
    html += '<div class="card-body">';
    if (treeMode) {
        html += '<div id="interArrivalTreeContainer" class="small"></div>';
    } else {
        const distribution = interArrival.distribution || 'expon';
        html += '<div class="mb-3">';
        html += '<label class="form-label small">Distribution</label>';
        html += renderFamilySelect('arrival', ARRIVAL, distribution);
        html += '</div>';
        html += renderDistributionParameters('arrival', ARRIVAL, distribution, interArrival.parameters || {});
    }
    html += '</div>';
    html += '</div>';
    html += '</div>';

    html += '<div class="mb-12">';
    html += '<div class="card">';
    html += '<div class="card-header py-2">';
    html += '<h6 class="mb-0">Arrival Time Calendar</h6>';
    html += '</div>';
    html += '<div class="card-body">';
    html += '<div id="arrivalCalendarDisplay">';
    html += renderArrivalCalendar(interArrival.calendar || {});
    html += '</div>';
    html += '</div>';
    html += '</div>';
    html += '</div>';

    html += '</div>';

    container.innerHTML = html;
    if (treeMode) {
        renderDecisionTreeDistributionEditor(interArrival.distribution, document.getElementById('interArrivalTreeContainer'), 'arrival');
    }
}

function updateInterArrivalParam(param, value) {
    markParametersDirty();
    if (!state.parameters.inter_arrival_params) state.parameters.inter_arrival_params = {};
    const arrivalParams = state.parameters.inter_arrival_params;
    if (!arrivalParams.inter_arrival_time) arrivalParams.inter_arrival_time = { parameters: {} };
    editTimeDistribution(arrivalParams.inter_arrival_time, param, value);
}

registerDistributionKind('arrival', {
    update: (item, param, value) => updateInterArrivalParam(param, value),
    refresh: () => renderInterArrivalTimeParameters(state.parameters.inter_arrival_params),
});
