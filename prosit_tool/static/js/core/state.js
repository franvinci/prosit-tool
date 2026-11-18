/**
 * What the page is working on.
 *
 * One object shared by every module: the session that is open, its scenarios,
 * and the parameters of the scenario shown in the editor.
 */

export const state = {
    /** Id of the open session, or null on the upload screen. */
    sessionId: null,
    /** Parameters of the scenario in the editor, in the format of the API. */
    parameters: null,
    /** Scenarios of the session, as listed by /api/sessions/<id>/runs. */
    runs: [],
    /** Id of the scenario whose parameters are in the editor. */
    activeRunId: null,
    /** True from the first edit until the parameters are saved or reloaded. */
    dirty: false,
};

export const BASELINE_RUN_NAME = 'As-Is';

export function activeRun() {
    if (state.activeRunId == null) return null;
    return state.runs.find(r => r.id === state.activeRunId) || null;
}

export function isBaselineActive() {
    const run = activeRun();
    return !!(run && run.is_baseline);
}

/** The sections of the parameters that the editor changes and the server stores. */
export const EDITABLE_SECTIONS = [
    'transition_params',
    'resource_params',
    'execution_time_params',
    'waiting_time_params',
    'inter_arrival_params',
    'data_attribute_params',
];

/**
 * What is sent when a scenario is saved. The rest of `state.parameters` (the
 * drawing of the net, the accuracy metrics) is only shown, never stored.
 */
export function editableParameters(parameters = state.parameters) {
    const editable = {};
    for (const section of EDITABLE_SECTIONS) {
        if (parameters && parameters[section] !== undefined) editable[section] = parameters[section];
    }
    return editable;
}

let dirtyListener = () => {};

/** Call `listener(dirty)` whenever the unsaved-edits flag is set or cleared. */
export function onDirtyChange(listener) {
    dirtyListener = listener;
}

export function markParametersDirty() {
    if (state.dirty) return;
    state.dirty = true;
    dirtyListener(true);
}

export function clearParametersDirty() {
    state.dirty = false;
    dirtyListener(false);
}
