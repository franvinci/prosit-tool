/**
 * Running a simulation and downloading the event log it produces.
 */

import { postJson } from '../core/api.js';
import { on } from '../core/dom.js';
import { activeRun, isBaselineActive, state } from '../core/state.js';
import { showAlert } from '../core/ui.js';
import { loadAllVisualizations } from './results/index.js';
import { autoCreateWhatIfForRun, refreshWhatIfList, renderWhatIfList, saveParameters } from './scenarios.js';

// File name of the simulated log of the scenario on screen: what the two
// Download menus (card and sticky bar) serve.
let lastSimOutputFilename = null;

/** Set the simulated log that can be downloaded now (null: none yet). */
export function setSimOutputFilename(name) {
    lastSimOutputFilename = name || null;
    const stickyBtn = document.getElementById('stickyDownloadBtn');
    if (stickyBtn) stickyBtn.disabled = !lastSimOutputFilename;
    const stickyLabel = document.getElementById('stickyRunBtnLabel');
    if (stickyLabel) stickyLabel.textContent = lastSimOutputFilename ? 'Run Again' : 'Run Simulation';
}

function downloadSimulation(format) {
    if (!lastSimOutputFilename) return;
    const name = encodeURIComponent(lastSimOutputFilename);
    window.location.href = format === 'xes' ? `/api/download_xes/${name}` : `/api/download/${name}`;
}

/** The inputs exist twice, in the card and in the sticky bar: keep them in step. */
export function initSimulationControls() {
    const mirror = (firstId, secondId) => {
        const first = document.getElementById(firstId);
        const second = document.getElementById(secondId);
        if (!first || !second) return;
        second.value = first.value || second.value;
        first.addEventListener('input', () => { second.value = first.value; });
        second.addEventListener('input', () => { first.value = second.value; });
    };
    mirror('numInstances', 'stickyNumInstances');
    mirror('startTimestamp', 'stickyStartTimestamp');
}

function runSimulationFromSticky() {
    const main = document.getElementById('numInstances');
    const stickyN = document.getElementById('stickyNumInstances');
    if (stickyN && main && stickyN.value) main.value = stickyN.value;
    const mainTs = document.getElementById('startTimestamp');
    const stickyTs = document.getElementById('stickyStartTimestamp');
    if (stickyTs && mainTs) mainTs.value = stickyTs.value || '';
    runSimulation();
}

async function runSimulation() {
    if (!state.sessionId) {
        showAlert('No session available for simulation', 'warning');
        return;
    }

    // No scenario selected (Run clicked while the list was still loading):
    // get the list and take the baseline.
    if (state.activeRunId == null) {
        await refreshWhatIfList();
        const baseline = state.runs.find(r => r.is_baseline);
        if (baseline) state.activeRunId = baseline.id;
        renderWhatIfList();
    }

    // Unsaved edits are kept before running: on the read-only baseline they
    // become a new "What-If N" scenario, which is the one simulated; on a
    // what-if they are saved in place.
    if (state.dirty && isBaselineActive()) {
        const created = await autoCreateWhatIfForRun();
        if (!created) return;
    } else if (state.dirty) {
        await saveParameters();
        if (state.dirty) return;  // not saved: do not simulate something else
    }

    const runId = state.activeRunId;
    if (runId == null) {
        showAlert('No active scenario — try reloading the session.', 'warning');
        return;
    }

    const numInstances = parseInt(document.getElementById('numInstances').value);
    const startTimestamp = document.getElementById('startTimestamp').value;
    const progress = document.getElementById('simulationProgress');

    document.getElementById('simulationResults').style.display = 'none';
    progress.style.display = 'block';

    const requestBody = { num_instances: numInstances, run_id: runId };
    if (startTimestamp) requestBody.start_timestamp = startTimestamp;

    let result;
    try {
        result = await postJson(`/api/simulate/${state.sessionId}`, requestBody);
    } catch (error) {
        showAlert(`Simulation error: ${error.message}`, 'danger');
        return;
    } finally {
        progress.style.display = 'none';
    }

    // The simulation is done. From here on a problem is about showing it.
    if (state.activeRunId === runId) {
        const runName = (result.run && result.run.name) || activeRun()?.name || 'scenario';
        document.getElementById('simulationResultText').textContent =
            `${runName}: generated ${result.num_events} events in ${numInstances} instances.`;
        setSimOutputFilename(result.sim_output_filename);
        document.getElementById('simulationResults').style.display = 'block';
        document.getElementById('simulationResultsCard').style.display = 'block';
        await loadAllVisualizations();
    }
    await refreshWhatIfList();

    feather.replace();
    showAlert(result.message, 'success');
}

on('click', {
    'run-simulation': () => runSimulation(),
    'run-simulation-sticky': () => runSimulationFromSticky(),
    'download-simulation': (element) => downloadSimulation(element.dataset.format),
});
