/**
 * The KPI comparison of the accuracy card: real log against simulated log,
 * as a table and three charts.
 */

import { escapeHtml, initTooltipsIn, on } from '../../core/dom.js';
import { TIME_UNIT_LABELS, TIME_UNIT_SECONDS, getResultsTimeUnit } from './common.js';

// Kept to draw the comparison again when the time unit changes.
let lastKpiComparison = null;

export function renderKpiComparisonHtml(kpi) {
    lastKpiComparison = kpi;
    const unit = getResultsTimeUnit('kpiUnit');
    const unitLabel = TIME_UNIT_LABELS[unit] || 'min';
    const unitFactor = TIME_UNIT_SECONDS[unit] || 60;

    const fmtInt = (v) => Number.isFinite(v) ? Math.round(v).toLocaleString() : '—';
    const fmtFloat = (v, digits = 2) => Number.isFinite(v) ? v.toFixed(digits) : '—';
    const fmtTime = (sec) => Number.isFinite(sec) ? (sec / unitFactor).toFixed(2) : '—';
    const real = kpi.real;
    const sim = kpi.simulated;

    const rows = [
        { label: '# Cases', tip: 'Total number of cases in the log.', real: fmtInt(real.num_cases), sim: fmtInt(sim.num_cases) },
        { label: '# Events', tip: 'Total number of events in the log.', real: fmtInt(real.num_events), sim: fmtInt(sim.num_events) },
        { label: '# Activities', tip: 'Number of distinct activities in the log.', real: fmtInt(real.num_activities), sim: fmtInt(sim.num_activities) },
        { label: '# Resources', tip: 'Number of distinct resources in the log.', real: fmtInt(real.num_resources), sim: fmtInt(sim.num_resources) },
        { label: `Cycle time mean (${unitLabel})`, tip: 'Average case duration (first start to last end).', real: fmtTime(real.cycle_time_mean_sec), sim: fmtTime(sim.cycle_time_mean_sec) },
        { label: `Cycle time median (${unitLabel})`, tip: 'Median case duration.', real: fmtTime(real.cycle_time_median_sec), sim: fmtTime(sim.cycle_time_median_sec) },
        { label: 'Throughput (cases/day)', tip: 'Cases completed per day across the full time span of the log.', real: fmtFloat(real.throughput_cases_per_day, 2), sim: fmtFloat(sim.throughput_cases_per_day, 2) },
    ];

    let bodyHtml = '';
    rows.forEach(r => {
        bodyHtml += `
            <tr>
                <td class="fw-semibold">
                    ${escapeHtml(r.label)}
                    <i data-feather="info" class="ms-1"
                       data-bs-toggle="tooltip"
                       data-bs-placement="top"
                       title="${escapeHtml(r.tip)}"
                       style="cursor: help; width: 14px; height: 14px; color: var(--light-green);"></i>
                </td>
                <td>${r.real}</td>
                <td>${r.sim}</td>
            </tr>`;
    });

    const chartsHtml = kpi.charts ? `
        <div class="card-body">
            <div class="row g-3">
                <div class="col-md-6">
                    <div class="small fw-semibold text-muted mb-1">Cycle time distribution (${unitLabel})</div>
                    <div style="position: relative; height: 220px;">
                        <canvas id="kpiCycleTimeChart"></canvas>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="small fw-semibold text-muted mb-1">Case arrivals per day</div>
                    <div style="position: relative; height: 220px;">
                        <canvas id="kpiArrivalsChart"></canvas>
                    </div>
                </div>
                <div class="col-12">
                    <div class="small fw-semibold text-muted mb-1">Resource event counts (top 15)</div>
                    <div style="position: relative; height: 280px;">
                        <canvas id="kpiResourcesChart"></canvas>
                    </div>
                </div>
            </div>
        </div>` : '';

    return `
        <div class="row mt-2" id="kpiComparison">
            <div class="col-12">
                <div class="card shadow-sm">
                    <div class="card-header bg-info text-white d-flex justify-content-between align-items-center">
                        <h6 class="card-title mb-0">KPI Comparison — Real vs Simulated</h6>
                        <div class="d-flex align-items-center gap-2">
                            <label for="kpiUnit" class="small mb-0 text-white">Time unit</label>
                            <select id="kpiUnit" class="form-select form-select-sm" style="width: auto;" data-action="set-kpi-unit">
                                <option value="sec" ${unit === 'sec' ? 'selected' : ''}>Seconds</option>
                                <option value="min" ${unit === 'min' ? 'selected' : ''}>Minutes</option>
                                <option value="hour" ${unit === 'hour' ? 'selected' : ''}>Hours</option>
                                <option value="day" ${unit === 'day' ? 'selected' : ''}>Days</option>
                            </select>
                        </div>
                    </div>
                    <div class="card-body p-0">
                        <div class="table-responsive">
                            <table class="table table-striped table-sm mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th class="w-50">Metric</th>
                                        <th class="w-25">Real Log</th>
                                        <th class="w-25">Simulated Log</th>
                                    </tr>
                                </thead>
                                <tbody>${bodyHtml}</tbody>
                            </table>
                        </div>
                    </div>
                    ${chartsHtml}
                </div>
            </div>
        </div>`;
}

const kpiCharts = {};

export function initKpiCharts(kpi) {
    if (!kpi || !kpi.charts || !window.Chart) return;
    const unit = getResultsTimeUnit('kpiUnit');
    const unitLabel = TIME_UNIT_LABELS[unit] || 'min';
    const unitFactor = TIME_UNIT_SECONDS[unit] || 60;

    for (const key of Object.keys(kpiCharts)) {
        try { kpiCharts[key].destroy(); } catch (e) { /* already gone */ }
        delete kpiCharts[key];
    }

    const overlay = (realData, simData, label) => ({
        labels: label,
        datasets: [
            {
                label: 'Real', data: realData,
                backgroundColor: 'rgba(123, 44, 191, 0.5)',
                borderColor: '#7b2cbf', borderWidth: 1,
            },
            {
                label: 'Simulated', data: simData,
                backgroundColor: 'rgba(40, 167, 69, 0.45)',
                borderColor: '#28a745', borderWidth: 1,
            },
        ],
    });
    const baseOpts = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } } },
    };

    const ct = kpi.charts.cycle_time;
    const ctCanvas = document.getElementById('kpiCycleTimeChart');
    if (ct && ctCanvas) {
        const labels = ct.bin_centers_sec.map(s => (s / unitFactor).toFixed(1));
        kpiCharts.cycleTime = new Chart(ctCanvas, {
            type: 'bar',
            data: overlay(ct.real_counts, ct.simulated_counts, labels),
            options: {
                ...baseOpts,
                scales: {
                    x: { title: { display: true, text: `Cycle time (${unitLabel})`, font: { size: 11 } }, ticks: { maxTicksLimit: 8, font: { size: 10 } } },
                    y: { title: { display: true, text: 'Cases', font: { size: 11 } }, beginAtZero: true },
                },
            },
        });
    }

    const arr = kpi.charts.arrivals_per_day;
    const arrCanvas = document.getElementById('kpiArrivalsChart');
    if (arr && arrCanvas) {
        const labels = arr.days.map(d => d.slice(0, 10));
        kpiCharts.arrivals = new Chart(arrCanvas, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Real', data: arr.real,
                        borderColor: '#7b2cbf', backgroundColor: 'rgba(123, 44, 191, 0.15)',
                        fill: false, tension: 0.2, pointRadius: 1,
                    },
                    {
                        label: 'Simulated', data: arr.simulated,
                        borderColor: '#28a745', backgroundColor: 'rgba(40, 167, 69, 0.15)',
                        fill: false, tension: 0.2, pointRadius: 1,
                    },
                ],
            },
            options: {
                ...baseOpts,
                scales: {
                    x: { ticks: { maxTicksLimit: 8, font: { size: 10 } } },
                    y: { title: { display: true, text: 'Cases', font: { size: 11 } }, beginAtZero: true },
                },
            },
        });
    }

    const rc = kpi.charts.resource_counts;
    const rcCanvas = document.getElementById('kpiResourcesChart');
    if (rc && rcCanvas) {
        kpiCharts.resources = new Chart(rcCanvas, {
            type: 'bar',
            data: overlay(rc.real, rc.simulated, rc.resources),
            options: {
                ...baseOpts,
                indexAxis: 'y',
                scales: {
                    x: { title: { display: true, text: 'Events', font: { size: 11 } }, beginAtZero: true },
                    y: { ticks: { font: { size: 10 } } },
                },
            },
        });
    }
}

// Draw only the comparison again (after a change of time unit).
function rerenderKpiComparison() {
    if (!lastKpiComparison) return;
    const section = document.getElementById('kpiComparison');
    if (!section) return;
    const container = section.parentElement;
    section.outerHTML = renderKpiComparisonHtml(lastKpiComparison);
    feather.replace();
    initTooltipsIn(container);
    initKpiCharts(lastKpiComparison);
}

on('change', { 'set-kpi-unit': () => rerenderKpiComparison() });
