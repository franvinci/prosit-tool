/**
 * Results: the process map (directly-follows graph) of the simulated log.
 */

import { escapeHtml, on } from '../../core/dom.js';
import { renderDot } from '../../core/graphviz.js';
import { state } from '../../core/state.js';
import { loadResult } from './common.js';

// The server describes the map (DOT text); it is drawn here.
async function renderProcessMap(container, dot, message) {
    if (!dot) {
        container.innerHTML = `
            <div class="d-flex justify-content-center align-items-center h-100">
                <span class="text-muted">${escapeHtml(message || 'No process map available')}</span>
            </div>
        `;
        return;
    }

    const frame = document.createElement('div');
    frame.className = 'process-map-svg-container';
    frame.appendChild(await renderDot(dot));
    const centered = document.createElement('div');
    centered.className = 'text-center';
    centered.appendChild(frame);
    container.replaceChildren(centered);
}

/** Load the process map of the scenario on screen, with the edge metric chosen. */
export function loadProcessMap() {
    const select = document.getElementById('processMapAggregation');
    const aggregation = select ? select.value : 'median';
    const container = document.getElementById('processMapContainer');
    return loadResult(
        container, 'process map',
        `/api/get_visualization/${state.sessionId}/process_map?aggregation=${encodeURIComponent(aggregation)}`,
        (result) => renderProcessMap(container, result.dot, result.message),
    );
}

on('change', { 'reload-process-map': () => loadProcessMap() });
