/**
 * The accuracy card: how close the simulator is to the original log.
 *
 * The metrics are computed on request, after discovery (it can take minutes),
 * and are then kept with the session.
 */

import { request } from '../../core/api.js';
import { escapeHtml, initTooltipsIn, on } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { initKpiCharts, renderKpiComparisonHtml } from './kpi.js';

function metricsAreEmpty(metrics) {
    if (!metrics || typeof metrics !== 'object') return true;
    // One object per category: there are metrics if at least one has a value.
    return !Object.values(metrics).some(
        v => v && typeof v === 'object' && Object.keys(v).length > 0
    );
}

/**
 * Show the metrics; when there are none and `autoCompute` is set, ask the
 * server to compute them and show them when they arrive.
 */
export function renderAccuracyResults(metrics, sessionId, autoCompute) {
    const card = document.getElementById('accuracyCard');
    const container = document.getElementById('accuracyResultsContainer');

    if (metricsAreEmpty(metrics)) {
        if (autoCompute && sessionId !== undefined && sessionId !== null) {
            // The user asked for the metrics: show the card with a spinner
            // and start the computation. The server keeps the result with the
            // session, so a reload finds it.
            card.style.display = 'block';
            container.innerHTML = `
                <div class="d-flex align-items-center text-muted">
                    <div class="spinner-border spinner-border-sm me-2" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <span>Computing accuracy metrics... this can take a few minutes.</span>
                </div>`;
            fetchAndRenderMetrics(sessionId);
            return;
        }
        // Not asked for and not computed before: no card at all.
        container.innerHTML = '<p class="text-muted">No accuracy results available.</p>';
        card.style.display = 'none';
        return;
    }

    card.style.display = 'block';

    const categoriesOrder = ['control-flow', 'time', 'resource-flow', 'generalization'];
    const categoriesDisplay = {
        'control-flow': 'Control Flow',
        'time': 'Timing',
        'resource-flow': 'Resource Flow',
        'generalization': 'Generalization'
    };

    // Metric descriptions for tooltips
    const metricDescriptions = {
            // Control Flow Metrics
            '2gd': '2-Gram Distribution Distance: Quantifies the similarity between the 2-gram activity sequence distributions in the original and simulated logs. Values close to 0 indicate high similarity.',
            '3gd': '3-Gram Distribution Distance: Quantifies the similarity between the 3-gram activity sequence distributions in the original and simulated logs. Values close to 0 indicate high similarity.',

            // Time Metrics
            'ctd': 'Cycle Time Distribution Distance: Measures how closely the cycle time distributions of the original and simulated logs align. Lower values indicate higher similarity.',
            'car': 'Case Arrival Distribution Distance: Measures how closely the case arrival distributions of the original and simulated logs align. Lower values indicate higher similarity.',

            // Resource Flow Metrics
            'r2gd': '2-Gram Resource Distribution Distance: Quantifies the similarity between the 2-gram resource sequence distributions in the original and simulated logs. Values close to 0 indicate high similarity.',
            'r3gd': '3-Gram Resource Distribution Distance: Quantifies the similarity between the 3-gram resource sequence distributions in the original and simulated logs. Values close to 0 indicate high similarity.',

            // Generalization Metrics
            'ctd_entropy': 'Cycle Time Distribution Entropy: Entropy of the cycle time distribution in the simulated logs, indicating variability and unpredictability. Greater values indicate higher generalization.',
            'etd_entropy': 'Execution Time Distribution Entropy: Entropy of the event execution time distribution in the simulated logs, indicating variability and unpredictability. Greater values indicate higher generalization.',
    };

    let html = '<div class="row">';

    for (const category of categoriesOrder) {
        if (metrics[category]) {
            const data = metrics[category];
            const displayCategory = categoriesDisplay[category] || category;

            html += `
                <div class="col-lg-6 mb-4">
                    <div class="card h-100 shadow-sm">
                        <div class="card-header bg-info text-white">
                            <h6 class="card-title mb-0">${escapeHtml(displayCategory)}</h6>
                        </div>
                        <div class="card-body p-0">
                            <div class="table-responsive">
                                <table class="table table-striped table-sm mb-0">
                                    <thead class="table-light">
                                        <tr>
                                            <th class="w-50">Metric</th>
                                            <th class="w-50">Value</th>
                                        </tr>
                                    </thead>
                                    <tbody>
            `;

            for (const [metric, value] of Object.entries(data)) {
                const formattedMetric = metric.toUpperCase().replace(/_/g, ' ');
                const description = metricDescriptions[metric] || `Metric: ${formattedMetric}`;

                html += `
                                        <tr>
                                            <td class="w-50">
                                                ${escapeHtml(formattedMetric)}
                                                <i data-feather="info" class="ms-1"
                                                   data-bs-toggle="tooltip"
                                                   data-bs-placement="top"
                                                   title="${escapeHtml(description)}"
                                                   style="cursor: help; width: 14px; height: 14px; color: var(--light-green);"></i>
                                            </td>
                                            <td class="w-50">${parseFloat(value).toFixed(4)}</td>
                                        </tr>
                `;
            }

            html += `
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    html += '</div>';

    if (metrics.kpi_comparison && metrics.kpi_comparison.real && metrics.kpi_comparison.simulated) {
        html += renderKpiComparisonHtml(metrics.kpi_comparison);
    }

    container.innerHTML = html;

    // Initialize Feather icons for the new content
    feather.replace();

    // Initialize tooltips after adding the HTML
    initTooltipsIn(container);

    // Build the KPI comparison Chart.js charts (no-op if data missing).
    if (metrics.kpi_comparison) initKpiCharts(metrics.kpi_comparison);
}

async function fetchAndRenderMetrics(sessionId) {
    const container = document.getElementById('accuracyResultsContainer');
    try {
        const result = await request(`/api/metrics/${sessionId}`, { method: 'POST' });
        // It can take minutes: the user may have opened another session.
        if (state.sessionId !== sessionId) return;
        if (state.parameters) state.parameters.prosit_metrics = result.prosit_metrics;
        // Computed once: if nothing came out, say so instead of asking again.
        renderAccuracyResults(result.prosit_metrics, sessionId, false);
    } catch (err) {
        if (state.sessionId !== sessionId) return;
        container.innerHTML = `
            <div class="alert alert-warning mb-0">
                <div class="d-flex justify-content-between align-items-center">
                    <span>Failed to compute metrics: ${escapeHtml(err.message)}</span>
                    <button class="btn btn-sm btn-outline-secondary" data-action="compute-metrics">Retry</button>
                </div>
            </div>`;
    }
}

on('click', { 'compute-metrics': () => renderAccuracyResults({}, state.sessionId, true) });
