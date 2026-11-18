/**
 * Opening and deleting sessions (the "Recent Sessions" list).
 */

import { deleteResource, getJson } from '../core/api.js';
import { escapeHtml, on } from '../core/dom.js';
import { formatDateTime } from '../core/format.js';
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

const STATUS_COLOURS = { ready: 'success', completed: 'success', uploaded: 'warning', error: 'danger' };

function sessionRow(session) {
    const label = escapeHtml(session.label);
    const runs = session.run_count > 0 ? ` · ${session.run_count} run${session.run_count === 1 ? '' : 's'}` : '';
    return `
        <div class="list-group-item recent-session-item" data-session-id="${session.id}">
            <div class="d-flex justify-content-between align-items-start gap-2">
                <div class="recent-session-main flex-grow-1 cursor-pointer" data-action="load-session" data-session-id="${session.id}">
                    <h6 class="mb-1 text-truncate" title="${label}">${label}</h6>
                    <small class="text-muted d-block">${escapeHtml(formatDateTime(session.last_used_at))}${runs}</small>
                </div>
                <div class="d-flex flex-column align-items-end gap-1">
                    <span class="badge bg-${STATUS_COLOURS[session.status] || 'info'}">${escapeHtml(session.status)}</span>
                    <button type="button" class="btn btn-sm btn-link text-danger p-0 recent-session-delete" title="Delete session"
                            data-action="delete-session" data-session-id="${session.id}" data-session-label="${label}">
                        <i data-feather="trash-2" style="width: 14px; height: 14px;"></i>
                    </button>
                </div>
            </div>
        </div>`;
}

/**
 * Draw the "Recent Sessions" list from what the server has now. Called when
 * the page opens and after whatever changes it: an upload, a simulation, a
 * new or a deleted scenario.
 */
export async function refreshSessionsList() {
    const container = document.getElementById('sessionsList');
    if (!container) return;
    try {
        const { sessions } = await getJson('/api/sessions');
        container.innerHTML = sessions.length
            ? sessions.map(sessionRow).join('')
            : `<div class="list-group-item text-center text-muted py-3">
                   <small>No sessions yet — upload a log to get started.</small>
               </div>`;
        feather.replace();
    } catch (error) {
        console.warn('Failed to list the sessions:', error);
    }
}

async function deleteSession(sessionId, label) {
    if (!confirm(`Delete session "${label}"? All scenarios and simulation results will be removed.`)) return;
    try {
        await deleteResource(`/api/sessions/${sessionId}`);
        refreshSessionsList();
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

    state.parameters._compute_evaluation_requested = !!computeEval;

    // No simulation to download until loadSession() says there is one.
    setSimOutputFilename(null);
    clearParametersDirty();

    show('welcomeMessage', 'none');
    show('parametersCard', 'block');
    show('simulationCard', 'block');
    show('whatIfCard', 'block');
    show('stickyRunBar', 'block');
    // The results on screen belong to the session that was open before:
    // loadSession() shows the ones of this session, if it has any.
    show('simulationResultsCard', 'none');
    show('simulationResults', 'none');

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
