/**
 * Changing the shape of a decision tree: the dialog that turns a leaf into a
 * split, and the one that turns a split back into a leaf.
 */

import { escapeHtml, initTooltipsIn, on } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';
import { renderInterArrivalTimeParameters } from './arrival.js';
import { FAMILIES } from './distributions.js';
import { showActivityExecution } from './execution.js';
import { showResourceWeight } from './resources.js';
import { showTransitionWeights } from './transitions.js';
import { generateFeaturesForTreeType, getFeatureTooltip, isCategoricalFeature } from './tree-features.js';
import { addSplit, isTree, removeSplit, singleLeafTimeTree } from './trees.js';
import { showResourceWaiting } from './waiting.js';

const WEIGHT_TREES = ['transition', 'resource'];
const TIME_TREES = ['execution', 'waiting', 'arrival'];

function selected(selectId) {
    return document.getElementById(selectId).value;
}

/**
 * The tree being edited: the one of the entry selected in the tab that
 * `treeType` belongs to. An entry that is not a tree yet becomes one, with a
 * single leaf.
 */
function findTree(treeType) {
    const parameters = state.parameters;
    switch (treeType) {
        case 'transition':
            return parameters.transition_params.transition_weights[selected('transitionSelect')];
        case 'resource':
            return parameters.resource_params.resource_weights[selected('resourceWeightSelect')];
        case 'arrival': {
            if (!parameters.inter_arrival_params) parameters.inter_arrival_params = {};
            if (!parameters.inter_arrival_params.inter_arrival_time) parameters.inter_arrival_params.inter_arrival_time = {};
            const arrival = parameters.inter_arrival_params.inter_arrival_time;
            if (!isTree(arrival.distribution)) arrival.distribution = singleLeafTimeTree();
            return arrival.distribution;
        }
        case 'execution': {
            const durations = parameters.execution_time_params.activity_durations;
            const activity = selected('activityExecutionSelect');
            if (!isTree(durations[activity])) durations[activity] = singleLeafTimeTree();
            return durations[activity];
        }
        case 'waiting': {
            const waitingTimes = parameters.waiting_time_params.resource_waiting_times;
            const resource = selected('resourceWaitingSelect');
            if (!isTree(waitingTimes[resource])) waitingTimes[resource] = singleLeafTimeTree();
            return waitingTimes[resource];
        }
        default:
            return undefined;
    }
}

/** Draw again the tree that was just changed. */
function refreshTreeDisplay(treeType) {
    switch (treeType) {
        case 'transition': showTransitionWeights(selected('transitionSelect')); break;
        case 'resource': showResourceWeight(selected('resourceWeightSelect')); break;
        case 'arrival': renderInterArrivalTimeParameters(state.parameters.inter_arrival_params || {}); break;
        case 'execution': showActivityExecution(selected('activityExecutionSelect')); break;
        case 'waiting': showResourceWaiting(selected('resourceWaitingSelect')); break;
        default: break;
    }
    feather.replace();
}

function showModal(id, html) {
    const existing = document.getElementById(id);
    if (existing) existing.remove();
    document.body.insertAdjacentHTML('beforeend', html);
    const element = document.getElementById(id);
    new bootstrap.Modal(element).show();
    return element;
}

function hideModal(id) {
    bootstrap.Modal.getInstance(document.getElementById(id)).hide();
}

// What a new leaf holds: a field for a weight, or the place where
// setupDistributionControls() puts the fields of a distribution.
function leafValueInput(treeType, id) {
    return WEIGHT_TREES.includes(treeType)
        ? `<input type="number" class="form-control" id="${id}" min="0" max="1" step="0.001" value="0.5">`
        : `<div id="${id}Container"></div>`;
}

// The fields of the distribution of a new leaf; their ids start with `branch`.
function setupDistributionControls(containerId, branch, unitSuffix) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error('Container not found:', containerId);
        return;
    }
    container.innerHTML = `
        <div class="row">
            <div class="col-md-6">
                <label class="form-label small">Distribution</label>
                <select class="form-select form-select-sm" id="${branch}Distribution">
                    ${FAMILIES.map(([value, name]) => `<option value="${value}"${value === 'expon' ? ' selected' : ''}>${name}</option>`).join('')}
                </select>
            </div>
            <div class="col-md-6">
                <div id="${branch}Params"></div>
            </div>
        </div>
    `;

    const distSelect = document.getElementById(`${branch}Distribution`);
    const paramsContainer = document.getElementById(`${branch}Params`);

    function numInput(id, value, marginClass) {
        const cls = marginClass ? ` ${marginClass}` : '';
        if (unitSuffix) {
            return `<div class="input-group input-group-sm${cls}">
                        <input type="number" class="form-control" id="${id}" min="0" step="0.1" value="${value}">
                        <span class="input-group-text">${unitSuffix}</span>
                    </div>`;
        }
        return `<input type="number" class="form-control form-control-sm${cls}" id="${id}" min="0" step="0.1" value="${value}">`;
    }

    function renderParams() {
        const dist = distSelect.value;
        let html = '';

        if (dist === 'fixed') {
            html = `<label class="form-label small">Value</label>${numInput(`${branch}Value`, 15)}`;
        } else if (dist === 'norm') {
            html = `<label class="form-label small">Mean</label>${numInput(`${branch}Mean`, 15, 'mb-1')}
                    <label class="form-label small">Std Dev</label>${numInput(`${branch}Std`, 5, 'mb-1')}
                    <label class="form-label small">Min</label>${numInput(`${branch}Min`, 0, 'mb-1')}
                    <label class="form-label small">Max</label>${numInput(`${branch}Max`, 100)}`;
        } else if (dist === 'expon') {
            html = `<label class="form-label small">Mean</label>${numInput(`${branch}Mean`, 15, 'mb-1')}
                    <label class="form-label small">Min</label>${numInput(`${branch}Min`, 0, 'mb-1')}
                    <label class="form-label small">Max</label>${numInput(`${branch}Max`, 100)}`;
        } else if (dist === 'uniform') {
            html = `<label class="form-label small">Min</label>${numInput(`${branch}Min`, 0, 'mb-1')}
                    <label class="form-label small">Max</label>${numInput(`${branch}Max`, 100)}`;
        }

        paramsContainer.innerHTML = html;
    }

    distSelect.addEventListener('change', renderParams);
    renderParams();
}

// The leaf described by the fields whose ids start with `branch`.
function getDistributionValue(branch) {
    const field = (name) => document.getElementById(`${branch}${name}`);
    const dist = field('Distribution').value;
    const value = parseFloat(field('Value')?.value || field('Mean')?.value || 15);

    let params = {};
    let minValue = 0, maxValue = 100;

    if (dist === 'fixed') {
        params = { value: value };
        minValue = maxValue = value;
    } else if (dist === 'norm') {
        params = { mean: value, std: parseFloat(field('Std').value) };
        minValue = parseFloat(field('Min').value);
        maxValue = parseFloat(field('Max').value);
    } else if (dist === 'expon') {
        params = { mean: value };
        minValue = parseFloat(field('Min').value);
        maxValue = parseFloat(field('Max').value);
    } else if (dist === 'uniform') {
        minValue = parseFloat(field('Min').value);
        maxValue = parseFloat(field('Max').value);
        params = { min: minValue, max: maxValue };
    }

    return {
        value: value,
        dist: { dist_name: dist, params: params, min_value: minValue, max_value: maxValue },
    };
}

// The weight typed in the field `id`, or null (after telling the user) when
// it is not a number between 0 and 1.
function readWeight(id, message) {
    const weight = parseFloat(document.getElementById(id).value);
    if (isNaN(weight) || weight < 0 || weight > 1) {
        alert(message);
        return null;
    }
    return weight;
}

function addSplitToNode(nodeId, treeType) {
    const features = generateFeaturesForTreeType(treeType);

    // The list keeps the order of the features, under one heading per group.
    const groups = new Map();
    features.forEach(feature => {
        const group = feature.group || 'Other';
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group).push(feature);
    });
    const dropdownItemsHtml = [...groups].map(([group, items]) => {
        const header = `<li class="split-feature-group-header">${escapeHtml(group)}</li>`;
        return header + items.map(feature => (
            `<li><button type="button" class="dropdown-item small" data-value="${escapeHtml(feature.value)}" data-bs-toggle="tooltip" data-bs-placement="right" title="${escapeHtml(getFeatureTooltip(feature.value))}">${escapeHtml(feature.label)}</button></li>`
        )).join('');
    }).join('');
    const firstFeatureValue = features.length ? features[0].value : '';
    const firstFeatureLabel = features.length ? features[0].label : 'Choose a feature...';

    const modalEl = showModal('addSplitModal', `
        <div class="modal fade" id="addSplitModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Add New Split</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3 split-feature-dropdown">
                            <label for="splitFeatureBtn" class="form-label">Feature</label>
                            <div class="dropdown w-100">
                                <button class="form-select text-start" type="button" id="splitFeatureBtn"
                                        data-bs-toggle="dropdown" aria-expanded="false">
                                    <span id="splitFeatureLabel">${escapeHtml(firstFeatureLabel)}</span>
                                </button>
                                <input type="hidden" id="splitFeature" value="${escapeHtml(firstFeatureValue)}">
                                <ul class="dropdown-menu w-100 shadow-sm">
                                    ${dropdownItemsHtml}
                                </ul>
                            </div>
                        </div>
                        <div class="mb-3" id="thresholdGroup">
                            <label for="splitThreshold" class="form-label">Threshold (≤)</label>
                            <input type="number" class="form-control" id="splitThreshold" step="0.1" value="0.5">
                        </div>
                        <div class="mb-3">
                            <label for="trueValue" class="form-label">True Branch Value</label>
                            ${leafValueInput(treeType, 'trueValue')}
                        </div>
                        <div class="mb-3">
                            <label for="falseValue" class="form-label">False Branch Value</label>
                            ${leafValueInput(treeType, 'falseValue')}
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" data-action="confirm-add-split"
                                data-node-id="${escapeHtml(nodeId)}" data-tree-type="${escapeHtml(treeType)}">Add Split</button>
                    </div>
                </div>
            </div>
        </div>
    `);

    // The list of features is a dropdown of buttons: picking one stores it in
    // the hidden field and shows its name.
    const featureInput = document.getElementById('splitFeature');
    const featureLabel = document.getElementById('splitFeatureLabel');
    const thresholdGroup = document.getElementById('thresholdGroup');
    // A condition has no threshold: it holds or it does not.
    const syncThreshold = () => {
        thresholdGroup.style.display = isCategoricalFeature(featureInput.value) ? 'none' : 'block';
    };
    modalEl.querySelectorAll('.dropdown-menu .dropdown-item').forEach(button => {
        button.addEventListener('click', () => {
            featureInput.value = button.getAttribute('data-value');
            featureLabel.textContent = button.textContent;
            syncThreshold();
        });
    });
    syncThreshold();

    if (!WEIGHT_TREES.includes(treeType)) {
        const unit = TIME_TREES.includes(treeType) ? 'min' : null;
        setupDistributionControls('trueValueContainer', 'true', unit);
        setupDistributionControls('falseValueContainer', 'false', unit);
    }
    initTooltipsIn(modalEl);
}

function confirmAddSplit(nodeId, treeType) {
    const feature = document.getElementById('splitFeature').value;

    // A condition is stored with a threshold of 0.5, as prosit-pm does.
    let threshold = 0.5;
    if (!isCategoricalFeature(feature)) {
        threshold = parseFloat(document.getElementById('splitThreshold').value);
        if (isNaN(threshold)) {
            alert('Please enter a valid threshold');
            return;
        }
    }

    const tree = findTree(treeType);
    if (!tree) {
        console.error('Could not find tree data for treeType:', treeType);
        alert('Could not find tree data. Please try refreshing the page and try again.');
        return;
    }

    let trueLeaf, falseLeaf;
    if (WEIGHT_TREES.includes(treeType)) {
        const trueWeight = readWeight('trueValue', 'Values must be between 0 and 1');
        if (trueWeight === null) return;
        const falseWeight = readWeight('falseValue', 'Values must be between 0 and 1');
        if (falseWeight === null) return;
        trueLeaf = { value: trueWeight };
        falseLeaf = { value: falseWeight };
    } else {
        trueLeaf = getDistributionValue('true');
        falseLeaf = getDistributionValue('false');
    }

    addSplit(tree, nodeId, feature, threshold, trueLeaf, falseLeaf);
    markParametersDirty();

    hideModal('addSplitModal');
    refreshTreeDisplay(treeType);
}

function removeSplitFromNode(nodeId, treeType) {
    if (!confirm('Are you sure you want to remove this split? This will delete the entire subtree.')) {
        return;
    }
    if (!findTree(treeType)) {
        alert('Could not find tree data');
        return;
    }

    // The split becomes a leaf again: ask what the leaf holds.
    showModal('removeSplitModal', `
        <div class="modal fade" id="removeSplitModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Set New Leaf Value</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label for="newLeafValue" class="form-label">New Value</label>
                            ${leafValueInput(treeType, 'newLeafValue')}
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" data-action="confirm-remove-split"
                                data-node-id="${escapeHtml(nodeId)}" data-tree-type="${escapeHtml(treeType)}">Remove Split</button>
                    </div>
                </div>
            </div>
        </div>
    `);

    if (!WEIGHT_TREES.includes(treeType)) {
        setupDistributionControls('newLeafValueContainer', 'newLeaf', TIME_TREES.includes(treeType) ? 'min' : null);
    }
}

function confirmRemoveSplit(nodeId, treeType) {
    const tree = findTree(treeType);
    if (!tree) {
        alert('Could not find tree data');
        return;
    }

    let leaf;
    if (WEIGHT_TREES.includes(treeType)) {
        const weight = readWeight('newLeafValue', 'Value must be between 0 and 1');
        if (weight === null) return;
        leaf = { value: weight };
    } else {
        leaf = getDistributionValue('newLeaf');
    }

    removeSplit(tree, nodeId, leaf);
    markParametersDirty();

    hideModal('removeSplitModal');
    refreshTreeDisplay(treeType);
}

on('click', {
    'add-tree-split': (element) => addSplitToNode(element.dataset.nodeId, element.dataset.treeType),
    'confirm-add-split': (element) => confirmAddSplit(element.dataset.nodeId, element.dataset.treeType),
    'remove-tree-split': (element) => removeSplitFromNode(element.dataset.nodeId, element.dataset.treeType),
    'confirm-remove-split': (element) => confirmRemoveSplit(element.dataset.nodeId, element.dataset.treeType),
});
