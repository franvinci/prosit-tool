/**
 * Shared by the Simulation Results tabs: time units, the scenario the charts
 * refer to, loading a chart with its spinner and its error, and the histogram
 * most tabs draw.
 */

import { ApiError, getJson } from '../../core/api.js';
import { escapeHtml } from '../../core/dom.js';
import { state } from '../../core/state.js';

export const TIME_UNIT_LABELS = { sec: 'sec', min: 'min', hour: 'hr', day: 'd' };
export const TIME_UNIT_SECONDS = { sec: 1, min: 60, hour: 3600, day: 86400 };

/** Unit chosen in the given select, minutes when there is none. */
export function getResultsTimeUnit(elementId) {
    if (elementId) {
        const sel = document.getElementById(elementId);
        if (sel && sel.value) return sel.value;
    }
    return 'min';
}

/**
 * Add the scenario on screen to a results URL. Without one (a session with no
 * scenarios yet) the server uses the scenario simulated last.
 */
export function withRunId(url) {
    if (state.activeRunId == null) return url;
    return url + (url.includes('?') ? '&' : '?') + 'run_id=' + encodeURIComponent(state.activeRunId);
}

const SPINNER = `
    <div class="d-flex justify-content-center align-items-center h-100" style="min-height: 200px;">
        <div class="spinner-border text-info" role="status"><span class="visually-hidden">Loading...</span></div>
    </div>`;

/**
 * Load one result into its container: a spinner while the answer comes, then
 * whatever `render(result)` draws; if it cannot be drawn, the reason, in the
 * same place. A failure here never looks like a failed simulation.
 */
export async function loadResult(container, what, url, render) {
    container.innerHTML = SPINNER;
    try {
        const result = await getJson(withRunId(url));
        await render(result);
    } catch (error) {
        const refused = error instanceof ApiError && error.status > 0;
        const message = refused ? error.message : `Failed to load ${what}: ${error.message}`;
        container.innerHTML = `<div class="alert alert-${refused ? 'warning' : 'danger'} mb-0">${escapeHtml(message)}</div>`;
    }
}

// Charts of the results tabs by canvas id: a tab is redrawn on a new canvas,
// and the chart of the previous one has to be released.
const resultCharts = {};

export function destroyResultChart(canvasId) {
    const existing = resultCharts[canvasId];
    if (existing) { try { existing.destroy(); } catch (e) { /* already gone */ } }
    resultCharts[canvasId] = null;
}

export function keepResultChart(canvasId, chart) {
    resultCharts[canvasId] = chart;
}

const CHART_PURPLE = '#7b2cbf';
const CHART_PURPLE_BG = 'rgba(123, 44, 191, 0.45)';

function renderHistogramChart(canvasId, binCenters, counts, xLabel, title) {
    destroyResultChart(canvasId);
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const labels = binCenters.map(v => Number(v).toFixed(1));
    keepResultChart(canvasId, new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: title || 'Frequency',
                data: counts,
                backgroundColor: CHART_PURPLE_BG,
                borderColor: CHART_PURPLE,
                borderWidth: 1,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, title: title ? { display: true, text: title, font: { size: 12 } } : { display: false } },
            scales: {
                x: { title: { display: true, text: xLabel, font: { size: 11 } }, ticks: { maxTicksLimit: 10, font: { size: 10 } } },
                y: { title: { display: true, text: 'Frequency', font: { size: 11 } }, beginAtZero: true },
            },
        },
    }));
}

/** Mean, median, minimum and maximum under a histogram. */
function renderMetricsRow(metrics, unitLabel) {
    const cell = (name, value) => `
            <div class="col-md-3">
                <div class="fw-bold text-success">${name}</div>
                <div class="text-muted">${Number(value).toFixed(2)} ${escapeHtml(unitLabel)}</div>
            </div>`;
    return `
        <div class="row text-center mt-3">${cell('Mean', metrics.mean)}${cell('Median', metrics.median)}${cell('Min', metrics.min)}${cell('Max', metrics.max)}
        </div>`;
}

/** Draw a histogram with its summary row into `container`. */
export function renderHistogramResult(container, canvasId, result, { metrics, unitLabel, xLabel, title }) {
    container.innerHTML = `
        <div style="position: relative; height: 320px;">
            <canvas id="${canvasId}"></canvas>
        </div>
        ${renderMetricsRow(metrics, unitLabel)}
    `;
    const histogram = result.histogram || { bin_centers: [], counts: [] };
    renderHistogramChart(canvasId, histogram.bin_centers, histogram.counts, xLabel, title);
}
