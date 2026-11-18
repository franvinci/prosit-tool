/**
 * Results: when a resource works, as events per weekday and hour.
 */

import { escapeHtml, on } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { destroyResultChart, keepResultChart, loadResult } from './common.js';

export function loadResourceHeatmap() {
    if (!state.sessionId) return Promise.resolve();
    const select = document.getElementById('resourceHeatmapSelect');
    const resourceName = select ? select.value : '';
    const params = new URLSearchParams();
    if (resourceName) params.append('resource', resourceName);
    const query = params.toString();

    const container = document.getElementById('resourceHeatmap');
    return loadResult(
        container, 'resource heatmap',
        `/api/get_visualization/${state.sessionId}/resource_heatmap${query ? '?' + query : ''}`,
        (result) => {
            const titleSuffix = result.resource ? ` — ${result.resource}` : ' — All resources';
            container.innerHTML = `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div class="small fw-semibold text-muted">Events per weekday × hour${escapeHtml(titleSuffix)}</div>
                </div>
                <div style="position: relative; height: 320px;">
                    <canvas id="resourceHeatmapCanvas"></canvas>
                </div>`;
            renderHeatmapChart('resourceHeatmapCanvas', result.matrix, result.weekday_labels, result.hours, result.max_value);
        },
    );
}

function renderHeatmapChart(canvasId, matrix, weekdayLabels, hours, maxValue) {
    destroyResultChart(canvasId);
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const data = [];
    for (let r = 0; r < (matrix || []).length; r++) {
        for (let c = 0; c < matrix[r].length; c++) {
            data.push({ x: hours[c], y: weekdayLabels[r], v: matrix[r][c] });
        }
    }
    const max = Math.max(1, maxValue || 1);
    function colorFor(v) {
        // YlGnBu-ish ramp; light at low, dark teal at high.
        const t = Math.min(1, Math.max(0, v / max));
        const r = Math.round(255 - 255 * t);
        const g = Math.round(255 - 90 * t);
        const b = Math.round(217 - 50 * t);
        return `rgba(${r},${g},${b},${0.25 + 0.6 * t})`;
    }
    keepResultChart(canvasId, new Chart(canvas, {
        type: 'matrix',
        data: {
            datasets: [{
                label: 'Events',
                data,
                backgroundColor: ctx => colorFor(ctx.raw.v),
                borderColor: 'rgba(255,255,255,0.4)',
                borderWidth: 1,
                width: ctx => (ctx.chart.chartArea || {}).width / 24 - 1,
                height: ctx => (ctx.chart.chartArea || {}).height / 7 - 1,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { title: () => '', label: ctx => `${ctx.raw.y} ${ctx.raw.x}:00 — ${ctx.raw.v} events` } },
            },
            scales: {
                x: {
                    type: 'linear',
                    min: -0.5, max: 23.5,
                    ticks: { stepSize: 1, font: { size: 10 } },
                    title: { display: true, text: 'Hour of day', font: { size: 11 } },
                    grid: { display: false },
                },
                y: {
                    type: 'category',
                    labels: weekdayLabels,
                    offset: true,
                    ticks: { font: { size: 11 } },
                    grid: { display: false },
                },
            },
        },
    }));
}

on('change', { 'reload-resource-heatmap': () => loadResourceHeatmap() });
