/**
 * What-if scenarios: the chips that list them, and creating, opening,
 * renaming, saving and deleting one.
 */

import { deleteResource, getJson, patchJson, postJson, putJson } from '../core/api.js';
import { escapeHtml, on } from '../core/dom.js';
import { BASELINE_RUN_NAME, activeRun, clearParametersDirty, editableParameters, isBaselineActive, onDirtyChange, state } from '../core/state.js';
import { showAlert } from '../core/ui.js';
import { renderParameters } from './params/index.js';
import { loadAllVisualizations } from './results/index.js';
import { refreshSessionsList } from './sessions.js';
import { setSimOutputFilename } from './simulation.js';

/**
 * Draw the scenario picker: one chip per scenario, the active one highlighted;
 * every chip but the baseline has rename and delete buttons.
 */
export function renderWhatIfList() {
    const container = document.getElementById('whatIfList');
    const badge = document.getElementById('activeRunBadge');
    if (!container) return;

    if (!state.runs.length) {
        container.innerHTML = '<span class="text-muted small">No scenarios yet.</span>';
        if (badge) badge.style.display = 'none';
        return;
    }

    const sorted = [...state.runs].sort((a, b) => {
        if (a.is_baseline !== b.is_baseline) return a.is_baseline ? -1 : 1;
        return new Date(a.created_at || 0) - new Date(b.created_at || 0);
    });

    container.innerHTML = sorted.map(run => {
        const active = run.id === state.activeRunId;
        const cls = `whatif-chip ${active ? 'active' : ''} ${run.is_baseline ? 'baseline' : ''}`;
        const sub = run.has_simulation
            ? `<span class="whatif-chip-sub" title="${escapeHtml(run.num_instances || '')} instances">✓ simulated</span>`
            : '<span class="whatif-chip-sub text-muted">not run</span>';
        const actions = run.is_baseline ? '' : `
            <div class="whatif-chip-actions">
                <button type="button" class="whatif-chip-action whatif-chip-rename" title="Rename"
                        data-action="rename-scenario" data-run-id="${run.id}">
                    <i data-feather="edit-2" style="width:13px;height:13px;"></i>
                </button>
                <button type="button" class="whatif-chip-action whatif-chip-delete" title="Delete scenario"
                        data-action="delete-scenario" data-run-id="${run.id}">
                    <i data-feather="x" style="width:13px;height:13px;"></i>
                </button>
            </div>`;
        return `
            <div class="${cls}" data-action="switch-scenario" data-run-id="${run.id}" title="${run.is_baseline ? 'Baseline (read-only)' : 'Click to load'}">
                <div class="whatif-chip-name">${escapeHtml(run.name)}</div>
                <div class="whatif-chip-meta">${sub}</div>
                ${actions}
            </div>`;
    }).join('');

    // The badge in the header of the parameters card names the scenario shown.
    if (badge) {
        const run = activeRun();
        if (run) {
            badge.textContent = run.name;
            badge.style.display = 'inline-block';
            badge.classList.toggle('bg-light', run.is_baseline);
            badge.classList.toggle('text-success', run.is_baseline);
            badge.classList.toggle('bg-warning', !run.is_baseline);
            badge.classList.toggle('text-dark', !run.is_baseline);
        } else {
            badge.style.display = 'none';
        }
    }

    // "Save Changes" edits a what-if in place. The baseline is read-only:
    // edits made there become a new what-if when the simulation is run.
    const saveBtn = document.getElementById('saveParametersBtn');
    if (saveBtn) {
        saveBtn.style.display = (activeRun() && !isBaselineActive()) ? '' : 'none';
    }

    feather.replace();
}

/**
 * Read the scenarios of the session again, after one was created, renamed,
 * deleted or simulated. The list of the sessions shows how many there are and
 * the state of the session, so it is read again with them.
 */
export async function refreshWhatIfList() {
    if (!state.sessionId) return;
    refreshSessionsList();
    try {
        const body = await getJson(`/api/sessions/${state.sessionId}/runs`);
        state.runs = body.runs || [];
        renderWhatIfList();
    } catch (err) {
        console.warn('Failed to refresh runs:', err);
    }
}

function showSimulationResults(visible) {
    document.getElementById('simulationResultsCard').style.display = visible ? 'block' : 'none';
    document.getElementById('simulationResults').style.display = visible ? 'block' : 'none';
}

async function switchToWhatIf(runId) {
    if (runId === state.activeRunId) return;
    if (state.dirty) {
        if (!confirm('You have unsaved parameter edits. Switch scenarios anyway? Your edits will be discarded.')) {
            return;
        }
    }

    // The answer comes in a few tens of milliseconds: a mark on the chip is
    // enough, a blocking dialog would only flicker.
    const chip = document.querySelector(`.whatif-chip[data-run-id="${runId}"]`);
    if (chip) chip.classList.add('loading');

    try {
        const body = await getJson(`/api/runs/${runId}`);

        state.activeRunId = runId;
        state.parameters = body.parameters;
        clearParametersDirty();
        renderParameters(body.parameters);
        renderWhatIfList();
        feather.replace();

        const run = activeRun();
        setSimOutputFilename(run && run.simulation_df_filename ? run.simulation_df_filename : null);

        if (run && run.simulation_df_filename) {
            // Show the results card at once: each tab has its own spinner
            // while its chart loads, and the editor stays usable meanwhile.
            showSimulationResults(true);
            const resultText = document.getElementById('simulationResultText');
            if (resultText && run.num_instances) {
                resultText.textContent = `Last run: ${run.num_instances} instance${run.num_instances === 1 ? '' : 's'} (${run.name}).`;
            }
            loadAllVisualizations();  // not awaited
        } else {
            showSimulationResults(false);
        }
    } catch (err) {
        showAlert(`Failed to load scenario: ${err.message}`, 'danger');
    } finally {
        if (chip) chip.classList.remove('loading');
    }
}

function showCreateWhatIfModal() {
    if (!state.sessionId) {
        showAlert('Open a session first', 'warning');
        return;
    }
    const existing = document.getElementById('createWhatIfModal');
    if (existing) existing.remove();

    const sourceLabel = (activeRun() && activeRun().name) || BASELINE_RUN_NAME;
    const modalHtml = `
        <div class="modal fade" id="createWhatIfModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">New What-If Scenario</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Scenario name</label>
                            <input type="text" class="form-control" id="newWhatIfName" maxlength="100" placeholder="e.g. Reduce loan officers">
                            <div class="form-text">Pick a short, descriptive name. "${BASELINE_RUN_NAME}" is reserved.</div>
                        </div>
                        <div class="alert alert-info py-2 small mb-0">
                            The new scenario will be a copy of <strong>${escapeHtml(sourceLabel)}</strong>${state.dirty ? ' with your current unsaved edits applied' : ''}.
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" data-action="create-scenario">Create</button>
                    </div>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = new bootstrap.Modal(document.getElementById('createWhatIfModal'));
    modal.show();
    setTimeout(() => {
        const input = document.getElementById('newWhatIfName');
        if (input) input.focus();
    }, 250);
}

async function createWhatIfFromModal() {
    const nameInput = document.getElementById('newWhatIfName');
    const name = (nameInput.value || '').trim();
    if (!name) {
        showAlert('Please enter a name', 'warning');
        return;
    }
    const body = { name };
    // The copy always carries the edits made so far, saved or not.
    if (state.parameters) body.parameters = editableParameters();
    if (state.activeRunId != null) body.from_run_id = state.activeRunId;

    try {
        const result = await postJson(`/api/sessions/${state.sessionId}/runs`, body);

        const modal = bootstrap.Modal.getInstance(document.getElementById('createWhatIfModal'));
        if (modal) modal.hide();
        // The edits made so far are in the new scenario: opening it loses
        // nothing, so there is nothing to confirm.
        clearParametersDirty();
        await refreshWhatIfList();
        await switchToWhatIf(result.run.id);
        showAlert(`Created scenario "${result.run.name}"`, 'success');
    } catch (err) {
        showAlert(`Failed to create scenario: ${err.message}`, 'danger');
    }
}

async function renameWhatIf(runId) {
    const run = state.runs.find(r => r.id === runId);
    if (!run) return;
    const next = prompt('New scenario name:', run.name);
    if (next == null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === run.name) return;

    try {
        await patchJson(`/api/runs/${runId}`, { name: trimmed });
        await refreshWhatIfList();
    } catch (err) {
        showAlert(`Rename failed: ${err.message}`, 'danger');
    }
}

async function deleteWhatIf(runId) {
    const run = state.runs.find(r => r.id === runId);
    if (!run || run.is_baseline) return;
    if (!confirm(`Delete scenario "${run.name}"? This will remove its parameters and any simulation result.`)) return;

    try {
        await deleteResource(`/api/runs/${runId}`);

        // Deleting the scenario on screen brings back the baseline.
        if (runId === state.activeRunId) {
            const baseline = state.runs.find(r => r.is_baseline);
            if (baseline) {
                await refreshWhatIfList();
                await switchToWhatIf(baseline.id);
            } else {
                state.activeRunId = null;
                await refreshWhatIfList();
            }
        } else {
            await refreshWhatIfList();
        }
        showAlert('Scenario deleted', 'info', 2500);
    } catch (err) {
        showAlert(`Delete failed: ${err.message}`, 'danger');
    }
}

export async function saveParameters() {
    if (!state.sessionId || !state.parameters) {
        showAlert('No parameters to save', 'warning');
        return;
    }
    if (isBaselineActive()) {
        // The baseline is read-only on purpose. Edits made there are kept by
        // running the simulation (which copies them into a new what-if) or
        // with "+ New Scenario".
        showAlert('The As-Is baseline is read-only. Click Run, or "+ New Scenario", to save your edits as a what-if.', 'warning', 4500);
        return;
    }
    if (state.activeRunId == null) {
        showAlert('No active scenario', 'warning');
        return;
    }

    try {
        await putJson(`/api/runs/${state.activeRunId}`, { parameters: editableParameters() });
        clearParametersDirty();
        showAlert('Scenario parameters saved', 'success');
    } catch (error) {
        showAlert(`Error saving parameters: ${error.message}`, 'danger');
    }
}

function nextDefaultWhatIfName() {
    const re = /^What-If\s+(\d+)$/i;
    let max = 0;
    state.runs.forEach(r => {
        const m = (r.name || '').match(re);
        if (m) {
            const n = parseInt(m[1], 10);
            if (Number.isFinite(n) && n > max) max = n;
        }
    });
    return `What-If ${max + 1}`;
}

/**
 * Running the simulation with edits on the read-only baseline: keep them in a
 * new scenario named "What-If N", without asking (it can be renamed from its
 * chip). Returns false if the scenario could not be created.
 */
export async function autoCreateWhatIfForRun() {
    const name = nextDefaultWhatIfName();
    try {
        const body = await postJson(`/api/sessions/${state.sessionId}/runs`, {
            name, parameters: editableParameters(), from_run_id: state.activeRunId,
        });

        state.activeRunId = body.run.id;
        await refreshWhatIfList();
        clearParametersDirty();
        showAlert(`Saved edits as "${body.run.name}"`, 'info', 3000);
        return true;
    } catch (err) {
        showAlert(`Failed to create scenario: ${err.message}`, 'danger');
        return false;
    }
}

// The two "unsaved edits" hints: under the scenarios and in the parameters card.
onDirtyChange((dirty) => {
    const hint = document.getElementById('whatIfDirtyHint');
    if (hint) hint.style.display = dirty ? 'flex' : 'none';
    const headerHint = document.getElementById('parametersDirtyHeader');
    if (headerHint) headerHint.style.display = dirty ? 'inline-flex' : 'none';
});

on('click', {
    'new-scenario': () => showCreateWhatIfModal(),
    'create-scenario': () => createWhatIfFromModal(),
    'switch-scenario': (element) => switchToWhatIf(Number(element.dataset.runId)),
    'rename-scenario': (element) => renameWhatIf(Number(element.dataset.runId)),
    'delete-scenario': (element) => deleteWhatIf(Number(element.dataset.runId)),
    'save-parameters': () => saveParameters(),
});
