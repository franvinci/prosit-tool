/**
 * Results: the process map (directly-follows graph) of the simulated log.
 */

import { escapeHtml, on } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { loadResult } from './common.js';

function renderProcessMap(container, processMap, message) {
    if (!processMap) {
        container.innerHTML = `
            <div class="d-flex justify-content-center align-items-center h-100">
                <span class="text-muted">${escapeHtml(message || 'No process map available')}</span>
            </div>
        `;
        return;
    }

    // The server sends the drawing as SVG.
    container.innerHTML = `
        <div class="text-center">
            <div class="process-map-svg-container" style="border: 1px solid #dee2e6; border-radius: 8px; background: white; padding: 10px; margin-bottom: 15px;">
                ${processMap}
            </div>
        </div>
    `;
}

/** Load the process map of the scenario on screen, with the edge metric chosen. */
export function loadProcessMap() {
    const select = document.getElementById('processMapAggregation');
    const aggregation = select ? select.value : 'median';
    const container = document.getElementById('processMapContainer');
    return loadResult(
        container, 'process map',
        `/api/get_visualization/${state.sessionId}/process_map?aggregation=${encodeURIComponent(aggregation)}`,
        (result) => renderProcessMap(container, result.visualization, result.message),
    );
}

on('change', { 'reload-process-map': () => loadProcessMap() });
