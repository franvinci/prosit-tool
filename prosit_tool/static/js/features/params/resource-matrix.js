/**
 * The matrix of the "Resources" tab: which resource performs which activity,
 * and how many cases each resource handles at once. Rows and columns can be
 * filtered.
 */

import { escapeHtml, infoIcon, initTooltipsIn } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';

const CONCURRENCY_HELP = 'Maximum number of cases a resource can handle simultaneously. 1 = single task, ≥2 = multitasking.';

/** HTML of the matrix; attachMatrixHandlers() makes it work once it is in the page. */
export function renderResourceActivityMatrix(resources, activityNames, actToResources, maxConcurrency) {
    function buildMultiSelect(type, allLabel, items) {
        let html = `<div class="dropdown matrix-multiselect" data-multiselect-type="${type}">
            <button class="form-select form-select-sm text-start matrix-multiselect-btn" type="button"
                    data-bs-toggle="dropdown" data-bs-auto-close="outside" aria-expanded="false"
                    style="width: 220px;">
                <span class="matrix-multiselect-label">${escapeHtml(allLabel)}</span>
            </button>
            <ul class="dropdown-menu p-2 shadow-sm" style="max-height: 320px; overflow-y: auto; min-width: 240px;">
                <li><div class="form-check">
                    <input class="form-check-input matrix-multiselect-all" type="checkbox" checked>
                    <label class="form-check-label small fw-bold ms-1">(All)</label>
                </div></li>
                <li><hr class="dropdown-divider my-1"></li>`;
        items.forEach(item => {
            const safe = escapeHtml(item);
            html += `<li><div class="form-check">
                <input class="form-check-input matrix-multiselect-item" type="checkbox" data-value="${safe}" checked>
                <label class="form-check-label small text-truncate ms-1" title="${safe}">${escapeHtml(item)}</label>
            </div></li>`;
        });
        html += `</ul></div>`;
        return html;
    }

    let html = '<div class="card">';
    html += '<div class="card-header py-2 d-flex justify-content-between align-items-center flex-wrap gap-2">';
    html += '<h6 class="mb-0">Activity &harr; Resource Assignments</h6>';
    html += '<div class="d-flex gap-2 align-items-center flex-wrap">';
    html += buildMultiSelect('activity', 'All activities', activityNames);
    html += buildMultiSelect('resource', 'All resources', resources);
    html += '</div>';
    html += '</div>';

    if (activityNames.length === 0 || resources.length === 0) {
        html += '<div class="card-body"><div class="alert alert-info mb-0"><small>No activities or resources to display. Activities will be assigned to all resources by default during simulation.</small></div></div></div>';
        return html;
    }

    // Build assigned set for fast lookup
    const assignedSet = {};
    activityNames.forEach(act => { assignedSet[act] = new Set(actToResources[act] || []); });

    html += '<div class="card-body p-0 resource-matrix-scroll">';
    html += '<table class="table table-sm table-bordered mb-0 resource-matrix">';

    // Header row: corner + per-resource header with max-concurrency input
    html += '<thead><tr>';
    html += '<th class="sticky-left sticky-corner small text-muted" style="min-width:220px;">Activity \\ Resource</th>';
    resources.forEach(resource => {
        const safeAttr = escapeHtml(resource);
        const cval = (maxConcurrency[resource] != null ? maxConcurrency[resource] : 1);
        html += `<th class="text-center" data-resource="${safeAttr}" style="min-width:130px;">
            <div class="small fw-bold text-truncate" title="${safeAttr}" style="max-width: 150px; margin: 0 auto;">${escapeHtml(resource)}</div>
            <div class="d-flex align-items-center justify-content-center mt-1" title="Max concurrent cases">
                <span class="text-muted small me-1">max</span>
                <input type="number" class="form-control form-control-sm matrix-max-concurrency"
                       min="1" step="1" style="width: 60px;" value="${cval}">
            </div>
        </th>`;
    });
    html += '</tr></thead>';

    // Body
    html += '<tbody>';
    activityNames.forEach(activity => {
        const safeAttr = escapeHtml(activity);
        html += `<tr data-activity="${safeAttr}">`;
        html += `<th class="sticky-left small fw-normal text-truncate" title="${safeAttr}" style="max-width:240px;">${escapeHtml(activity)}</th>`;
        resources.forEach(resource => {
            const isAssigned = assignedSet[activity].has(resource);
            const safeRes = escapeHtml(resource);
            html += `<td class="text-center" data-resource="${safeRes}">
                <input type="checkbox" class="form-check-input matrix-cell"${isAssigned ? ' checked' : ''}>
            </td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table>';
    html += '</div></div>';

    html += `<div class="form-text mt-2">${infoIcon(CONCURRENCY_HELP)} Use the matrix to (un)assign resources to activities and adjust per-resource max concurrent cases. Filters apply to rows and columns independently.</div>`;
    return html;
}

export function attachMatrixHandlers(scope) {
    // One listener for the whole table: it can have thousands of cells.
    const table = scope.querySelector('.resource-matrix');
    if (table) {
        table.addEventListener('change', (e) => {
            const input = e.target;
            if (input.classList.contains('matrix-cell')) {
                const tr = input.closest('tr');
                const td = input.closest('td');
                if (tr && td) updateActivityResource(tr.getAttribute('data-activity'), td.getAttribute('data-resource'), input.checked);
            } else if (input.classList.contains('matrix-max-concurrency')) {
                const th = input.closest('th');
                if (th) updateMaxConcurrency(th.getAttribute('data-resource'), input.value);
            }
        });
    }

    // The two filters: a list of checkboxes each, with "(All)" on top. Only
    // the checked activities (rows) and resources (columns) are shown.
    const dropdowns = scope.querySelectorAll('.matrix-multiselect');
    function applyMatrixFilters() {
        const selected = { activity: null, resource: null };
        dropdowns.forEach(dd => {
            const type = dd.getAttribute('data-multiselect-type');
            const items = Array.from(dd.querySelectorAll('.matrix-multiselect-item'));
            const checked = items.filter(c => c.checked).map(c => c.getAttribute('data-value'));
            // null means "all"
            selected[type] = (checked.length === items.length) ? null : new Set(checked);
        });

        scope.querySelectorAll('.resource-matrix tbody tr[data-activity]').forEach(tr => {
            const a = tr.getAttribute('data-activity');
            tr.style.display = (!selected.activity || selected.activity.has(a)) ? '' : 'none';
        });
        const hidden = new Set();
        scope.querySelectorAll('.resource-matrix thead th[data-resource]').forEach(th => {
            const r = th.getAttribute('data-resource');
            const visible = !selected.resource || selected.resource.has(r);
            th.style.display = visible ? '' : 'none';
            if (!visible) hidden.add(r);
        });
        scope.querySelectorAll('.resource-matrix tbody td[data-resource]').forEach(td => {
            td.style.display = hidden.has(td.getAttribute('data-resource')) ? 'none' : '';
        });
    }

    function refreshDropdownLabel(dd) {
        const type = dd.getAttribute('data-multiselect-type');
        const items = Array.from(dd.querySelectorAll('.matrix-multiselect-item'));
        const label = dd.querySelector('.matrix-multiselect-label');
        const all = dd.querySelector('.matrix-multiselect-all');
        const checked = items.filter(c => c.checked);
        if (all) {
            all.checked = checked.length === items.length;
            all.indeterminate = checked.length > 0 && checked.length < items.length;
        }
        if (!label) return;
        if (checked.length === items.length) {
            label.textContent = type === 'activity' ? 'All activities' : 'All resources';
        } else if (checked.length === 0) {
            label.textContent = '(none)';
        } else if (checked.length === 1) {
            label.textContent = checked[0].nextElementSibling.textContent;
        } else {
            label.textContent = `${checked.length} selected`;
        }
    }

    dropdowns.forEach(dd => {
        const allCb = dd.querySelector('.matrix-multiselect-all');
        const items = Array.from(dd.querySelectorAll('.matrix-multiselect-item'));
        if (allCb) {
            allCb.addEventListener('change', () => {
                items.forEach(c => { c.checked = allCb.checked; });
                refreshDropdownLabel(dd);
                applyMatrixFilters();
            });
        }
        items.forEach(c => {
            c.addEventListener('change', () => {
                refreshDropdownLabel(dd);
                applyMatrixFilters();
            });
        });
        // A click anywhere on the line of an item toggles it.
        dd.querySelectorAll('.dropdown-menu li').forEach(li => {
            li.addEventListener('click', (e) => {
                if (e.target.closest('input, label')) return;
                const cb = li.querySelector('input[type="checkbox"]');
                if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
            });
        });
        refreshDropdownLabel(dd);
    });
    initTooltipsIn(scope);
}

/** How many cases a resource handles at the same time (at least one). */
function updateMaxConcurrency(resource, value) {
    if (!state.parameters.resource_params.max_concurrency) {
        state.parameters.resource_params.max_concurrency = {};
    }
    let n = parseInt(value, 10);
    if (!Number.isFinite(n) || n < 1) {
        n = 1;
    }
    state.parameters.resource_params.max_concurrency[resource] = n;
    markParametersDirty();
}

function updateActivityResource(activity, resource, isAssigned) {
    if (!state.parameters.resource_params.act_to_resources) {
        state.parameters.resource_params.act_to_resources = {};
    }

    if (!state.parameters.resource_params.act_to_resources[activity]) {
        state.parameters.resource_params.act_to_resources[activity] = [];
    }

    const resources = state.parameters.resource_params.act_to_resources[activity];
    const index = resources.indexOf(resource);

    if (isAssigned && index === -1) {
        resources.push(resource);
    } else if (!isAssigned && index !== -1) {
        resources.splice(index, 1);
    }
    markParametersDirty();
}

/** The activities a resource performs. */
export function returnActivitiesPerResource(resource) {
    const assignments = state.parameters.resource_params.act_to_resources || {};
    return Object.keys(assignments).filter(activity => assignments[activity].includes(resource));
}
