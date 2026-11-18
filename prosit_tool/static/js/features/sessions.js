/**
 * Opening and deleting sessions (the "Recent Sessions" list).
 */

import { deleteResource, getJson } from '../core/api.js';
import { on } from '../core/dom.js';
import { activeRun, clearParametersDirty, state } from '../core/state.js';
import { showAlert } from '../core/ui.js';
import { renderParameters } from './params/index.js';
import { loadAllVisualizations } from './results/index.js';
import { refreshWhatIfList, renderWhatIfList } from './scenarios.js';
import { setSimOutputFilename } from './simulation.js';

function show(id, display) {
    const element = document.getElementById(id);
    if (element) element.style.display = display;
}

async function deleteSession(sessionId, label) {
    if (!confirm(`Delete session "${label}"? All scenarios and simulation results will be removed.`)) return;
    try {
        await deleteResource(`/api/sessions/${sessionId}`);
        const item = document.querySelector(`.recent-session-item[data-session-id="${sessionId}"]`);
        if (item) item.remove();
        if (sessionId === state.sessionId) {
            state.sessionId = null;
            state.parameters = null;
            state.runs = [];
            state.activeRunId = null;
            for (const id of ['parametersCard', 'simulationCard', 'whatIfCard', 'accuracyCard', 'simulationResultsCard', 'stickyRunBar']) {
                show(id, 'none');
            }
            show('welcomeMessage', 'block');
            setSimOutputFilename(null);
        }
        showAlert('Session deleted', 'info', 2500);
    } catch (err) {
        showAlert(`Delete failed: ${err.message}`, 'danger');
    }
}

async function loadSession(sessionId) {
    try {
        const result = await getJson(`/api/parameters/${sessionId}`);

        // The answer carries the baseline scenario together with the list of
        // what-if scenarios: no second request is needed for them.
        state.runs = result.runs || [];
        const initialActive = result.active_run_id ?? (state.runs.find(r => r.is_baseline) || state.runs[0] || {}).id;
        state.activeRunId = initialActive ?? null;

        await loadSessionData(sessionId, result.parameters, false);
        setSimOutputFilename(result.simulation_df_filename || null);

        // If the scenario has been simulated already, show its results again.
        if (result.simulation_df_filename) {
            show('simulationResultsCard', 'block');
            show('simulationResults', 'block');
            const resultText = document.getElementById('simulationResultText');
            if (resultText) {
                const run = activeRun();
                resultText.textContent = run && run.num_instances
                    ? `Last run: ${run.num_instances} instance${run.num_instances === 1 ? '' : 's'} (${run.name}).`
                    : 'Previous simulation results restored.';
            }
            loadAllVisualizations();  // not awaited
        } else {
            show('simulationResultsCard', 'none');
            show('simulationResults', 'none');
        }
    } catch (error) {
        showAlert(`Error loading session: ${error.message}`, 'danger');
    }
}

/** Put a session on the page: its parameters, its scenarios, the cards that depend on them. */
export async function loadSessionData(sessionId, parameters, computeEval) {
    state.sessionId = sessionId;
    state.parameters = parameters;
    state.originalVisualization = parameters.process_model.visualization;

    state.parameters._compute_evaluation_requested = !!computeEval;

    // No simulation to download until loadSession() says there is one.
    setSimOutputFilename(null);
    clearParametersDirty();

    show('welcomeMessage', 'none');
    show('parametersCard', 'block');
    show('simulationCard', 'block');
    show('whatIfCard', 'block');
    show('stickyRunBar', 'block');

    renderParameters(parameters);

    // After an upload the scenarios are not known yet; when a session is
    // opened from the list they came with the parameters.
    if (!state.runs.length || state.activeRunId == null) {
        await refreshWhatIfList();
        if (state.activeRunId == null) {
            const baseline = state.runs.find(r => r.is_baseline);
            state.activeRunId = baseline ? baseline.id : (state.runs[0] ? state.runs[0].id : null);
        }
    }
    renderWhatIfList();
    feather.replace();
}

on('click', {
    'load-session': (element) => loadSession(Number(element.dataset.sessionId)),
    'delete-session': (element) => deleteSession(Number(element.dataset.sessionId), element.dataset.sessionLabel),
});
