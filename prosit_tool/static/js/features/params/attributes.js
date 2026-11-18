/**
 * Parameters tab "Trace Attributes": how the attributes of a case are drawn.
 * A categorical attribute has a probability per value (the sliders keep them
 * summing to one), a numeric one has a distribution; each has a small chart.
 */

import { attrSelector, escapeHtml } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';
import { registerDistributionKind, renderDistributionParameters, renderFamilySelect } from './distribution-editor.js';
import { distributionPdf, distributionRange, mergeDistParams } from './distributions.js';

export function renderDataAttributeParameters(dataParams) {
    const container = document.getElementById('dataParams');
    if (!dataParams || !dataParams.distribution_data_attributes) {
        container.innerHTML = '<p class="text-muted">No trace attribute parameters available.</p>';
        return;
    }

    const categoricalAttrs = dataParams.label_data_attributes_categorical || [];
    const distributions = dataParams.distribution_data_attributes || {};
    const isEmpirical = dataParams.distribution_mode === 'empirical';
    let html = '<h6 class="mb-3">Case Attribute Distributions</h6>';

    if (isEmpirical) {
        html += `
            <div class="alert alert-info py-2 small">
                <strong>Empirical mode:</strong> attributes are sampled jointly from observed value combinations.
                Editing per attribute isn't available; the original samples are preserved on save.
            </div>`;
    }

    destroyAttributeCharts();

    for (const [attribute, params] of Object.entries(distributions)) {
        const isCategorical = categoricalAttrs.includes(attribute);
        const empiricalEntry = !!(params && typeof params === 'object' && params.type === 'empirical');
        const safeAttr = escapeHtml(attribute);
        const canvasId = attributeChartCanvasId(attribute);
        html += `
            <div class="card mb-3" data-attribute="${safeAttr}">
                <div class="card-header py-2 d-flex justify-content-between align-items-center">
                    <h6 class="mb-0">${escapeHtml(attribute)}</h6>
                    ${empiricalEntry ? '<span class="badge bg-secondary">empirical · read-only</span>' : ''}
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-7" data-attribute-controls="${safeAttr}">
        `;

        if (empiricalEntry) {
            html += '<p class="text-muted small mb-0">Sampled from joint empirical distribution at simulation time.</p></div><div class="col-md-5"></div></div></div></div>';
            continue;
        }

        if (isCategorical) {
            // {type: 'categorical', values: {...}}; sessions saved long ago
            // have the bare {value: probability} object instead.
            const values = (params && typeof params === 'object' && params.values && typeof params.values === 'object')
                ? params.values
                : (params || {});
            html += `<div class="row" data-cat-attribute="${escapeHtml(attribute)}">`;
            for (const [category, probability] of Object.entries(values)) {
                const safeCat = escapeHtml(category);
                const probNum = parseFloat(probability) || 0;
                html += `
                    <div class="col-md-6 mb-3" data-category="${safeCat}">
                        <label class="form-label small mb-1 text-truncate d-block" title="${safeCat}">${escapeHtml(category)}</label>
                        <div class="d-flex align-items-center gap-2">
                            <input type="range" class="form-range cat-prob-range" min="0" max="1" step="0.001" value="${probNum}">
                            <input type="number" class="form-control form-control-sm cat-prob-number" min="0" max="1" step="0.001" style="width: 90px;" value="${probNum}">
                        </div>
                    </div>
                `;
            }
            html += '</div>';
        } else { // Numeric/Distribution
            const distribution = params.distribution || 'norm';
            html += `
                <div class="row">
                    <div class="col-md-6">
                        <label class="form-label small">Distribution</label>
                        ${renderFamilySelect('attribute', attribute, distribution)}
                    </div>
                    <div class="col-md-6">
                        ${renderDistributionParameters('attribute', attribute, distribution, params.parameters || params)}
                    </div>
                </div>
            `;
        }
        // The controls on the left, the chart of the attribute on the right.
        html += `</div>
                        <div class="col-md-5 d-flex flex-column align-items-center justify-content-center">
                            <div style="width: 200px; height: 200px;">
                                <canvas id="${canvasId}" width="200" height="200"></canvas>
                            </div>
                            <div class="cat-chart-legend small mt-2 text-center" data-attribute-legend="${safeAttr}" style="max-width: 240px;"></div>
                        </div>
                    </div>
                </div>
            </div>`;
    }
    container.innerHTML = html;
    attachCategoricalSliderHandlers(container);
    renderAllAttributeCharts(distributions, categoricalAttrs);
}

const attributeCharts = {};

function attributeChartCanvasId(attribute) {
    return 'attrChart_' + String(attribute).replace(/[^a-zA-Z0-9_-]/g, '_');
}

function destroyAttributeCharts() {
    Object.values(attributeCharts).forEach(c => { try { c.destroy(); } catch (_) {} });
    Object.keys(attributeCharts).forEach(k => delete attributeCharts[k]);
}

const ATTRIBUTE_CHART_PALETTE = [
    '#7b2cbf', '#06d6a0', '#5fb3a3', '#c77dff', '#048a81',
    '#5a189a', '#f8961e', '#43aa8b', '#577590', '#f94144',
    '#9d4edd', '#1b9aaa', '#ef476f', '#ffd166', '#118ab2',
];

function renderAttributeLegend(attribute, labels, colors, values) {
    const legend = document.querySelector(attrSelector('data-attribute-legend', attribute));
    if (!legend) return;
    const total = values.reduce((a, b) => a + b, 0) || 1;
    legend.innerHTML = labels.map((lbl, i) => {
        const pct = ((values[i] / total) * 100).toFixed(1);
        return `<span class="d-inline-block me-2 mb-1" style="white-space: nowrap;">
            <span style="display:inline-block; width:10px; height:10px; background:${colors[i]}; border-radius:2px; vertical-align:middle; margin-right:4px;"></span>
            <span title="${escapeHtml(lbl)}">${escapeHtml(lbl)}</span>
            <span class="text-muted">(${pct}%)</span>
        </span>`;
    }).join('');
}

function renderCategoricalPieChart(attribute, values) {
    const canvas = document.getElementById(attributeChartCanvasId(attribute));
    if (!canvas || !window.Chart) return;
    if (attributeCharts[attribute]) {
        attributeCharts[attribute].destroy();
    }
    const labels = Object.keys(values);
    const data = labels.map(k => parseFloat(values[k]) || 0);
    const colors = labels.map((_, i) => ATTRIBUTE_CHART_PALETTE[i % ATTRIBUTE_CHART_PALETTE.length]);
    attributeCharts[attribute] = new Chart(canvas.getContext('2d'), {
        type: 'pie',
        data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 1 }] },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 1,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0) || 1;
                            const pct = (ctx.parsed / total) * 100;
                            return `${ctx.label}: ${ctx.parsed.toFixed(3)} (${pct.toFixed(1)}%)`;
                        }
                    }
                }
            }
        }
    });
    renderAttributeLegend(attribute, labels, colors, data);
}

function updateCategoricalPieChart(attribute, values) {
    const chart = attributeCharts[attribute];
    if (!chart) return renderCategoricalPieChart(attribute, values);
    const labels = Object.keys(values);
    const data = labels.map(k => parseFloat(values[k]) || 0);
    chart.data.labels = labels;
    chart.data.datasets[0].data = data;
    chart.update('none');
    const colors = labels.map((_, i) => ATTRIBUTE_CHART_PALETTE[i % ATTRIBUTE_CHART_PALETTE.length]);
    renderAttributeLegend(attribute, labels, colors, data);
}

function renderNumericPdfChart(attribute, distribution, params) {
    const canvas = document.getElementById(attributeChartCanvasId(attribute));
    if (!canvas || !window.Chart) return;
    if (attributeCharts[attribute]) {
        attributeCharts[attribute].destroy();
        delete attributeCharts[attribute];
    }
    // No list of colours for a density: the legend names the family.
    const legend = document.querySelector(attrSelector('data-attribute-legend', attribute));
    if (legend) legend.innerHTML = `<span class="text-muted">${escapeHtml(distribution)} PDF</span>`;

    const range = distributionRange(distribution, params);
    if (!range) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#888';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No preview for this distribution', canvas.width / 2, canvas.height / 2);
        return;
    }
    const N = 120;
    const [xMin, xMax] = range;
    const step = (xMax - xMin) / (N - 1);
    const xs = [], ys = [];
    for (let i = 0; i < N; i++) {
        const x = xMin + step * i;
        xs.push(x);
        ys.push(distributionPdf(distribution, params, x));
    }
    attributeCharts[attribute] = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: xs.map(x => x.toFixed(2)),
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
            maintainAspectRatio: true,
            aspectRatio: 1,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
                x: { ticks: { maxTicksLimit: 5, font: { size: 9 } }, grid: { display: false } },
                y: { ticks: { display: false }, grid: { display: false } }
            }
        }
    });
}

function renderAllAttributeCharts(distributions, categoricalAttrs) {
    if (!window.Chart) return;
    Object.entries(distributions).forEach(([attribute, params]) => {
        if (params && typeof params === 'object' && params.type === 'empirical') return;
        const isCategorical = categoricalAttrs.includes(attribute);
        if (isCategorical) {
            const values = (params && typeof params === 'object' && params.values && typeof params.values === 'object')
                ? params.values
                : (params || {});
            renderCategoricalPieChart(attribute, values);
        } else {
            const distribution = params.distribution || 'norm';
            const distParams = params.parameters || params || {};
            renderNumericPdfChart(attribute, distribution, distParams);
        }
    });
}

function attachCategoricalSliderHandlers(scope) {
    scope.querySelectorAll('[data-cat-attribute]').forEach(group => {
        const attribute = group.getAttribute('data-cat-attribute');
        const cells = Array.from(group.querySelectorAll('[data-category]'));

        function applyValuesToUI(values) {
            cells.forEach((cell, i) => {
                const v = values[i];
                const r = cell.querySelector('.cat-prob-range');
                const n = cell.querySelector('.cat-prob-number');
                if (r) r.value = v;
                if (n) n.value = v;
            });
        }

        function persistAll(values) {
            const valueMap = {};
            cells.forEach((cell, i) => {
                const cat = cell.getAttribute('data-category');
                valueMap[cat] = values[i];
                updateDataAttributeParam(attribute, true, null, values[i], cat);
            });
            updateCategoricalPieChart(attribute, valueMap);
        }

        function distributeFromIndex(editedIdx, rawValue) {
            let v = parseFloat(rawValue);
            if (!Number.isFinite(v)) v = 0;
            if (v < 0) v = 0;
            if (v > 1) v = 1;

            const current = cells.map(c => parseFloat(c.querySelector('.cat-prob-number').value) || 0);
            const next = current.slice();
            next[editedIdx] = v;

            const remaining = Math.max(0, 1 - v);
            let sumOthers = 0;
            for (let i = 0; i < current.length; i++) if (i !== editedIdx) sumOthers += current[i];

            if (sumOthers > 0) {
                // The others keep their proportions and share what is left.
                const factor = remaining / sumOthers;
                for (let i = 0; i < next.length; i++) {
                    if (i !== editedIdx) next[i] = current[i] * factor;
                }
            } else {
                // The others were all zero: they share what is left equally.
                const otherCount = next.length - 1;
                const eq = otherCount > 0 ? remaining / otherCount : 0;
                for (let i = 0; i < next.length; i++) {
                    if (i !== editedIdx) next[i] = eq;
                }
            }

            applyValuesToUI(next);
            persistAll(next);
        }

        cells.forEach((cell, idx) => {
            const range = cell.querySelector('.cat-prob-range');
            const number = cell.querySelector('.cat-prob-number');
            if (!range || !number) return;
            range.addEventListener('input', () => distributeFromIndex(idx, range.value));
            number.addEventListener('change', () => distributeFromIndex(idx, number.value));
        });

        applyValuesToUI(cells.map(c => parseFloat(c.querySelector('.cat-prob-number').value) || 0));
    });
}

/**
 * Store one edit of an attribute and draw the tab again: the probability of
 * `category` for a categorical attribute, otherwise the family
 * (`param` 'distribution') or one parameter of its distribution.
 */
function updateDataAttributeParam(attribute, isCategorical, param, value, category = null) {
    markParametersDirty();
    if (!state.parameters.data_attribute_params) {
        state.parameters.data_attribute_params = {};
    }
    if (!state.parameters.data_attribute_params.distribution_data_attributes) {
        state.parameters.data_attribute_params.distribution_data_attributes = {};
    }

    if (isCategorical) {
        const dist = state.parameters.data_attribute_params.distribution_data_attributes;
        if (!dist[attribute] || typeof dist[attribute] !== 'object' || !dist[attribute].values) {
            // Missing, or the bare object of old sessions: give it its type.
            const legacy = (dist[attribute] && typeof dist[attribute] === 'object') ? dist[attribute] : {};
            dist[attribute] = { type: 'categorical', values: { ...legacy } };
        }
        dist[attribute].values[category] = parseFloat(value);
        return;
    }

    if (!state.parameters.data_attribute_params.distribution_data_attributes[attribute]) {
        state.parameters.data_attribute_params.distribution_data_attributes[attribute] = {};
    }

    const targetObject = state.parameters.data_attribute_params.distribution_data_attributes[attribute];

    if (param === 'distribution') {
        const oldParams = targetObject.parameters || {};
        targetObject.distribution = value;
        targetObject.parameters = mergeDistParams(oldParams, value);
    } else {
        if (!targetObject.parameters) {
            targetObject.parameters = {};
        }
        targetObject.parameters[param] = parseFloat(value);

        // A fixed value is its own minimum and maximum.
        if (targetObject.distribution === 'fixed' && param === 'value') {
            targetObject.parameters.min = value;
            targetObject.parameters.max = value;
        }

    }

    renderDataAttributeParameters(state.parameters.data_attribute_params);
}

// The fields of a numeric attribute come from the shared distribution editor.
// Every edit draws the tab again already, so there is nothing to refresh.
registerDistributionKind('attribute', {
    update: (attribute, param, value) => updateDataAttributeParam(attribute, false, param, value),
    refresh: () => {},
});
