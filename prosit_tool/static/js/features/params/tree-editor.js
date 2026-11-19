/**
 * The editor of a decision tree.
 *
 * A split shows its condition and, when it is opened, the two branches under
 * it; it can be removed. A tree opens with every split closed. A leaf holds
 * what the tree decides for the cases that reach it: a weight (transition and
 * resource trees) or a distribution (time trees), editable in place; a leaf
 * can also be turned into a new split.
 */

import { escapeHtml, initTooltipsIn, on } from '../../core/dom.js';
import { markParametersDirty } from '../../core/state.js';
import { FAMILIES, distributionPdf, distributionRange, isOptionalBound, leafFields, leafParamsFromProsit } from './distributions.js';
import { getFeatureTooltip, splitCondition } from './tree-features.js';
import { isSplitOpen, setSplitOpen, shownBranches } from './trees.js';

const TIME_TREE_TYPES = ['execution', 'waiting', 'arrival'];

// For the element that holds the branches of a split: the tree and the node it
// belongs to, and how to draw the branches if they have not been drawn yet.
// (The branches of a closed split are drawn only when it is opened: the
// leaves of a deep tree are many, and each time leaf draws a chart.)
const splitOf = new WeakMap();

function indentedBlock() {
    const wrapper = document.createElement('div');
    wrapper.style.marginLeft = '12px';
    wrapper.style.borderLeft = '2px solid #eee';
    wrapper.style.paddingLeft = '8px';
    return wrapper;
}

function addSplitButton(id, treeType) {
    return `<button class="btn btn-sm btn-outline-primary" data-action="add-tree-split" data-node-id="${escapeHtml(id)}" data-tree-type="${escapeHtml(treeType)}" title="Add split">
                        <i data-feather="plus" class="me-1"></i>Add Split
                    </button>`;
}

/**
 * Draw `treeData` into `mountEl`. `createLeaf(node, id)` returns the element
 * that edits one leaf; `leafExplanation` completes the legend above the tree.
 */
function renderTree(treeData, mountEl, treeType, leafExplanation, createLeaf) {
    function createNode(id) {
        const node = treeData[id];
        const wrapper = indentedBlock();

        if (node && typeof node === 'object' && Object.prototype.hasOwnProperty.call(node, 'value')) {
            wrapper.appendChild(createLeaf(node, id));
        } else if (node && Object.prototype.hasOwnProperty.call(node, 'feature')) {
            // A condition holds or not; a number is compared with the threshold
            // (a whole number with the whole part of it: "≤ 1", not "≤ 1.5").
            const condition = escapeHtml(splitCondition(node.feature, node.threshold));

            const open = isSplitOpen(treeData, id);
            const title = document.createElement('div');
            title.innerHTML = `
                <div class="d-flex align-items-center gap-2">
                    <button class="btn btn-sm btn-outline-secondary tree-toggle" data-action="toggle-tree-node" title="Collapse/Expand">
                        <i data-feather="${open ? 'chevron-down' : 'chevron-right'}" class="tree-icon"></i>
                    </button>
                    <span class="badge bg-primary">Split</span>
                    <span data-bs-toggle="tooltip" data-bs-placement="top" title="${escapeHtml(getFeatureTooltip(node.feature, undefined, node.threshold))}" style="cursor: help; border-bottom: 1px dotted #adb5bd;">${condition}</span>
                    <button class="btn btn-sm btn-outline-danger" data-action="remove-tree-split" data-node-id="${escapeHtml(id)}" data-tree-type="${escapeHtml(treeType)}" title="Remove split">
                        <i data-feather="trash-2" class="me-1"></i>Remove
                    </button>
                </div>`;
            const childrenContainer = document.createElement('div');
            childrenContainer.className = open ? 'tree-children' : 'tree-children collapsed';
            childrenContainer.style.display = 'block';
            wrapper.appendChild(title);
            wrapper.appendChild(childrenContainer);

            const drawBranches = () => {
                if (!node.children) return;
                // "true" is the branch of the cases for which the condition
                // written above holds, whichever way prosit-pm stores it.
                const [holdsId, otherwiseId] = shownBranches(node);
                for (const [name, childId] of [['true', holdsId], ['false', otherwiseId]]) {
                    const label = document.createElement('div');
                    label.innerHTML = `<em>${name}</em>`;
                    childrenContainer.appendChild(label);
                    childrenContainer.appendChild(createNode(String(childId)));
                }
            };
            const split = { tree: treeData, id, draw: drawBranches };
            splitOf.set(childrenContainer, split);
            if (open) {
                split.draw = null;
                drawBranches();
            }
        } else {
            const unknown = document.createElement('div');
            unknown.textContent = 'Unknown node format';
            wrapper.appendChild(unknown);
        }
        return wrapper;
    }

    // The previews of the leaves that are about to go must be released first,
    // or their charts stay alive on canvases nobody shows.
    if (window.Chart) {
        mountEl.querySelectorAll('canvas.leaf-distribution-chart').forEach(canvas => {
            const chart = Chart.getChart(canvas);
            if (chart) chart.destroy();
        });
    }
    mountEl.replaceChildren();

    const header = document.createElement('div');
    header.className = 'mb-3';
    header.innerHTML = `
        <div class="alert alert-light py-2 mb-2 small border">
            <span class="badge bg-primary me-1">Split</span> condition learnt from the log &mdash; cases follow the <em>true</em> or <em>false</em> branch.
            <span class="badge bg-secondary ms-2 me-1">Leaf</span> ${leafExplanation}.
        </div>
        <div class="d-flex gap-2">
            <button class="btn btn-sm btn-outline-secondary" data-action="collapse-tree" title="Collapse All">
                <i data-feather="chevrons-up" class="me-1"></i>Collapse All
            </button>
            <button class="btn btn-sm btn-outline-secondary" data-action="expand-tree" title="Expand All">
                <i data-feather="chevrons-down" class="me-1"></i>Expand All
            </button>
        </div>
    `;
    mountEl.appendChild(header);
    mountEl.appendChild(createNode('0'));

    feather.replace();
    initTooltipsIn(mountEl);
}

/** A tree whose leaves are weights between 0 and 1 (transitions, resources). */
export function renderDecisionTreeEditor(treeData, mountEl, treeType = 'transition') {
    function createLeaf(node, id) {
        const value = (typeof node.value === 'number') ? node.value : parseFloat(node.value) || 0;
        const leaf = document.createElement('div');
        leaf.innerHTML = `
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <span class="badge bg-secondary">Leaf</span>
                    <span class="small">value:</span>
                    <input type="range" class="form-range" style="width: 160px;" min="0" max="1" step="0.001" value="${value}">
                    <input type="number" class="form-control form-control-sm" style="width: 90px;" step="0.001" min="0" max="1" value="${value}">
                    ${addSplitButton(id, treeType)}
                </div>`;
        const rangeInput = leaf.querySelector('input[type="range"]');
        const numberInput = leaf.querySelector('input[type="number"]');
        const persist = (raw) => {
            let v = parseFloat(raw);
            if (!Number.isFinite(v)) v = 0;
            v = Math.min(1, Math.max(0, v));
            treeData[id].value = v;
            markParametersDirty();
            if (numberInput.value !== String(v)) numberInput.value = v;
            if (rangeInput.value !== String(v)) rangeInput.value = v;
        };
        numberInput.addEventListener('change', () => persist(numberInput.value));
        rangeInput.addEventListener('input', () => persist(rangeInput.value));
        return leaf;
    }

    const leafExplanation = treeType === 'resource'
        ? 'resource selection weight (higher = picked more often)'
        : 'transition probability (sums to 1 across siblings)';
    renderTree(treeData, mountEl, treeType, leafExplanation, createLeaf);
}

// Draw the density of a leaf's distribution next to its fields.
function renderLeafDistributionChart(canvas, family, params) {
    if (!canvas || !window.Chart) return;
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    const range = distributionRange(family, params || {});
    const ctx = canvas.getContext('2d');
    if (!range) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#888';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No preview', canvas.width / 2, canvas.height / 2);
        return;
    }
    const N = 80;
    const [xMin, xMax] = range;
    const step = (xMax - xMin) / Math.max(1, N - 1);
    const xs = [], ys = [];
    for (let i = 0; i < N; i++) {
        const x = xMin + step * i;
        xs.push(x);
        ys.push(distributionPdf(family, params, x));
    }
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: xs.map(x => x.toFixed(1)),
            datasets: [{
                data: ys,
                borderColor: '#7b2cbf',
                backgroundColor: 'rgba(123, 44, 191, 0.15)',
                fill: true,
                tension: 0.25,
                pointRadius: 0,
                borderWidth: 2,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
                x: { ticks: { maxTicksLimit: 5, font: { size: 10 } }, grid: { display: false } },
                y: { ticks: { display: false }, grid: { display: false } }
            }
        }
    });
}

/** A tree whose leaves are distributions (execution, waiting and arrival times). */
export function renderDecisionTreeDistributionEditor(treeData, mountEl, treeType = 'distribution') {
    const unitSuffix = TIME_TREE_TYPES.includes(treeType) ? 'min' : null;

    function createLeaf(node, id) {
        if (!node.dist) {
            node.dist = { dist_name: 'expon', params: { mean: 15 }, min_value: 0, max_value: 100 };
        }

        const wrapper = indentedBlock();
        wrapper.innerHTML = `
            <div class="d-flex align-items-center gap-2">
                <span class="badge bg-secondary">Leaf</span>
                <span>distribution${unitSuffix ? ' <small class="text-muted">(minutes)</small>' : ''}</span>
                ${addSplitButton(id, treeType)}
            </div>
            <div class="row mt-2">
                <div class="col-md-6">
                    <select class="form-select form-select-sm mb-2">
                        ${FAMILIES.map(([value, name]) => `<option value="${value}"${node.dist.dist_name === value ? ' selected' : ''}>${name}</option>`).join('')}
                    </select>
                    <div class="leaf-params"></div>
                </div>
                <div class="col-md-6 d-flex align-items-center justify-content-center">
                    <div style="width: 100%; max-width: 320px; height: 220px;">
                        <canvas class="leaf-distribution-chart" style="width: 100%; height: 100%;"></canvas>
                    </div>
                </div>
            </div>`;
        const select = wrapper.querySelector('select');
        const paramsContainer = wrapper.querySelector('.leaf-params');
        const chartCanvas = wrapper.querySelector('canvas');

        // What the fields and the preview show. A leaf nobody edited keeps the
        // parameter list of prosit-pm, so that opening a leaf changes nothing
        // of what is saved; the first edit replaces the list with editable
        // parameters.
        function editableParams() {
            const stored = node.dist.params;
            if (Array.isArray(stored)) return leafParamsFromProsit(node.dist.dist_name, stored, node);
            return (stored && typeof stored === 'object') ? stored : {};
        }

        function updateLeafChart() {
            renderLeafDistributionChart(chartCanvas, node.dist.dist_name, editableParams());
        }

        function renderParams() {
            paramsContainer.replaceChildren();
            const family = select.value;
            const shown = editableParams();
            // Undefined when the leaf has no bound on that side.
            const low = node.dist.min_value ?? node.dist.min;
            const high = node.dist.max_value ?? node.dist.max;

            // What a field shows: the parameter if there is one, else the
            // bound or the value of the leaf it stands for, else a default.
            function current(key, fallback) {
                if (shown[key] != null) return shown[key];
                if (key === 'value') return node.value ?? fallback;
                return fallback;
            }

            for (const [label, key, limits, fallback] of leafFields(family, node.value, low, high)) {
                const optional = isOptionalBound(family, key);
                const withUnit = unitSuffix && key !== 'shape';
                const group = document.createElement('div');
                group.className = 'mb-2';
                group.innerHTML = `
                    <label class="form-label small">${label}</label>
                    ${withUnit ? '<div class="input-group input-group-sm">' : ''}
                    <input type="number" class="form-control${withUnit ? '' : ' form-control-sm'}"
                           ${limits.min !== undefined ? `min="${limits.min}" ` : ''}step="${limits.step || 0.1}">
                    ${withUnit ? `<span class="input-group-text">${unitSuffix}</span></div>` : ''}`;
                const input = group.querySelector('input');
                input.value = current(key, fallback) ?? (optional ? '' : 0);
                if (optional) {
                    // No bound: the distribution is not cut on that side.
                    input.placeholder = 'auto';
                    input.title = 'Sampled values are kept within this bound. Leave it empty for no bound.';
                }
                input.addEventListener('change', () => {
                    const value = parseFloat(input.value);
                    const emptied = optional && input.value === '';
                    if (isNaN(value) && !emptied) return;
                    // The first edit turns prosit-pm's list into editable parameters.
                    node.dist.params = editableParams();
                    if (emptied) {
                        delete node.dist.params[key];
                        delete node.dist[key === 'min' ? 'min_value' : 'max_value'];
                        markParametersDirty();
                        updateLeafChart();
                        return;
                    }
                    node.dist.params[key] = value;
                    if (key === 'min') node.dist.min_value = value;
                    if (key === 'max') node.dist.max_value = value;
                    if (family === 'fixed' && key === 'value') {
                        // The simulator reads a fixed leaf from the value of the leaf.
                        node.dist.min_value = value;
                        node.dist.max_value = value;
                        node.value = value;
                    }
                    markParametersDirty();
                    updateLeafChart();
                });
                paramsContainer.appendChild(group);
            }
        }

        select.addEventListener('change', () => {
            const family = select.value;
            // Read the parameters with the family the leaf had until now and
            // keep the ones the two families share. The shift is not one of
            // them: it was fitted for the previous family, and most families
            // have no field that shows it.
            const next = { ...editableParams() };
            delete next.loc;
            // The bounds of a fixed value are the value itself. Kept for
            // another family, they would turn it into the same constant.
            let bounded = true;
            if (node.dist.dist_name === 'fixed' || (node.dist.min_value != null && node.dist.min_value === node.dist.max_value)) {
                delete node.dist.min_value;
                delete node.dist.max_value;
                delete next.min;
                delete next.max;
                bounded = false;
            }
            node.dist.dist_name = family;
            if (family === 'fixed') {
                if (next.value == null) next.value = node.value ?? 1;
                node.dist.min_value = next.value;
                node.dist.max_value = next.value;
            } else if (family === 'norm') {
                if (next.mean == null) next.mean = node.value ?? 15;
                if (next.std == null) next.std = 5;
            } else if (family === 'expon') {
                if (next.mean == null) next.mean = node.value ?? 15;
            } else if (family === 'uniform') {
                // The two ends are the distribution: the old bounds when the
                // leaf had them, else an interval around its value.
                const around = node.value > 0 ? [node.value / 2, node.value * 1.5] : [0, 100];
                if (next.min == null) next.min = bounded ? (node.dist.min_value ?? around[0]) : around[0];
                if (next.max == null) next.max = bounded ? (node.dist.max_value ?? around[1]) : around[1];
                node.dist.min_value = next.min;
                node.dist.max_value = next.max;
            } else if (family === 'lognorm') {
                if (next.shape == null) next.shape = 0.5;
                if (next.loc == null) next.loc = 0;
                if (next.scale == null) next.scale = node.value ?? 1;
            } else if (family === 'gamma') {
                if (next.mean == null) next.mean = node.value ?? 15;
                if (next.std == null) next.std = 5;
            }
            node.dist.params = next;
            markParametersDirty();
            renderParams();
            updateLeafChart();
        });

        renderParams();
        // The canvas has no size until it is in the page.
        setTimeout(updateLeafChart, 0);
        return wrapper;
    }

    const what = {
        execution: 'execution time distribution',
        waiting: 'waiting time distribution',
        arrival: 'inter-arrival time distribution',
    }[treeType] || 'distribution';
    const leafExplanation = unitSuffix ? `${what} (in minutes) for cases reaching this leaf` : `${what} for cases reaching this leaf`;
    renderTree(treeData, mountEl, treeType, leafExplanation, createLeaf);
}

// The branches of a split are in the element right after its title.
function childrenOf(toggleButton) {
    let element = toggleButton.closest('.d-flex').parentElement;
    while (element && element.nextElementSibling) {
        element = element.nextElementSibling;
        if (element.classList.contains('tree-children')) return element;
    }
    return null;
}

// The button that opens and closes the branches held by `childrenContainer`.
function toggleOf(childrenContainer) {
    const title = childrenContainer.previousElementSibling;
    return title ? title.querySelector('.tree-toggle') : null;
}

function setCollapsed(toggleButton, childrenContainer, collapsed) {
    const split = splitOf.get(childrenContainer);
    if (split) {
        setSplitOpen(split.tree, split.id, !collapsed);
        if (!collapsed && split.draw) {
            // Opened for the first time: its branches are drawn now.
            const draw = split.draw;
            split.draw = null;
            draw();
        }
    }
    childrenContainer.classList.toggle('collapsed', collapsed);
    const icon = toggleButton && toggleButton.querySelector('.tree-icon');
    // Feather has replaced the <i> with an <svg>: put back an <i> for it to draw.
    if (icon) icon.outerHTML = `<i data-feather="${collapsed ? 'chevron-right' : 'chevron-down'}" class="tree-icon"></i>`;
}

// The icons and the tooltips of what has just been drawn.
function finishDrawing(container) {
    feather.replace();
    initTooltipsIn(container);
}

function toggleTreeNode(toggleButton) {
    const childrenContainer = childrenOf(toggleButton);
    if (!childrenContainer) return;
    setCollapsed(toggleButton, childrenContainer, !childrenContainer.classList.contains('collapsed'));
    finishDrawing(childrenContainer);
}

// Collapse or expand every split of the tree the button belongs to.
function setAllCollapsed(button, collapsed) {
    const tree = button.closest('.small') || document;
    if (collapsed) {
        tree.querySelectorAll('.tree-children:not(.collapsed)').forEach(childrenContainer => {
            setCollapsed(toggleOf(childrenContainer), childrenContainer, true);
        });
    } else {
        // Opening a split draws the splits under it, closed: go on until none is.
        let closed = tree.querySelectorAll('.tree-children.collapsed');
        while (closed.length) {
            closed.forEach(childrenContainer => setCollapsed(toggleOf(childrenContainer), childrenContainer, false));
            closed = tree.querySelectorAll('.tree-children.collapsed');
        }
    }
    finishDrawing(tree);
}

on('click', {
    'toggle-tree-node': (element) => toggleTreeNode(element),
    'collapse-tree': (element) => setAllCollapsed(element, true),
    'expand-tree': (element) => setAllCollapsed(element, false),
});
