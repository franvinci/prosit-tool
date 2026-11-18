/**
 * The upload form: picking an event log, mapping its columns, choosing the
 * discovery options, then uploading and discovering the parameters.
 */

import { getJson, request } from '../core/api.js';
import { formatFileSize } from '../core/format.js';
import { state } from '../core/state.js';
import { hideLoading, showAlert, showLoading, updateLoadingMessage } from '../core/ui.js';
import { loadSessionData, refreshSessionsList } from './sessions.js';
import { extractXesColumns, guessColumnMapping, parseCsvHeaderLine } from './upload-columns.js';

const CSV_MAPPING_SELECTS = {
    case_id: 'csvCaseIdCol',
    activity: 'csvActivityCol',
    end_ts: 'csvEndTsCol',
    start_ts: 'csvStartTsCol',
    resource: 'csvResourceCol',
};

// The columns a log may not have: they can be left out of the mapping.
const OPTIONAL_ROLES = ['start_ts', 'resource'];

const ACCEPTED_EXTENSIONS = {
    xesFile: { extensions: ['.xes', '.csv'], message: 'Please select a valid XES or CSV file' },
    pnmlFile: { extensions: ['.pnml'], message: 'Please select a valid PNML file' },
};
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

function byId(id) {
    return document.getElementById(id);
}

// A section of the form that stays in the layout when it does not apply: it is
// only dimmed and disabled, so that nothing around it moves.
function setSectionEnabled(section, input, enabled) {
    if (input) input.disabled = !enabled;
    if (section) {
        section.style.opacity = enabled ? '' : '0.5';
        section.style.pointerEvents = enabled ? '' : 'none';
    }
}

function showSliderValue(sliderId, valueId) {
    const slider = byId(sliderId);
    const value = byId(valueId);
    if (slider && value) slider.addEventListener('input', () => { value.textContent = slider.value; });
}

// Discovering the Petri net from the log, or importing it from a PNML file.
function initPetriNetSource() {
    const discoverNet = byId('discoverNet');
    const importNet = byId('importNet');
    if (!discoverNet || !importNet) return;

    const sync = () => {
        const importing = importNet.checked && !discoverNet.checked;
        byId('discoverySection').style.display = importing ? 'none' : 'block';
        byId('pnmlSection').style.display = importing ? 'block' : 'none';
        byId('uploadBtnText').textContent = importing ? 'Upload & Import' : 'Upload & Discover';
        const pnmlFile = byId('pnmlFile');
        if (pnmlFile) pnmlFile.required = importing;
    };
    discoverNet.addEventListener('change', sync);
    importNet.addEventListener('change', sync);
    sync();
}

// Incremental discovery needs decision trees (depth above 0); the grace
// period applies only to incremental discovery.
function initIncrementalDiscovery() {
    const maxDepthSelect = byId('maxDepthTree');
    const toggle = byId('incrementalDiscoveryToggle');
    if (!maxDepthSelect || !toggle) return;

    const sync = () => {
        const depth = parseInt(maxDepthSelect.value || '0');
        if (depth === 0) {
            toggle.checked = false;
            toggle.disabled = true;
        } else {
            toggle.disabled = false;
        }
        setSectionEnabled(byId('gracePeriodSection'), byId('gracePeriod'), toggle.checked && depth > 0);
    };
    maxDepthSelect.addEventListener('change', sync);
    toggle.addEventListener('change', sync);
    sync();
}

// The multitasking threshold applies only when multitasking is discovered.
function initMultitasking() {
    const toggle = byId('enableMultitaskingToggle');
    const section = byId('multitaskingThrSection');
    if (toggle && section) {
        const sync = () => setSectionEnabled(section, byId('multitaskingThr'), toggle.checked);
        toggle.addEventListener('change', sync);
        sync();
    }
    showSliderValue('multitaskingThr', 'multitaskingThrValue');
}

// Refuse a file of the wrong kind or size as soon as it is picked, and show
// under the field which file was picked.
function checkPickedFile(input) {
    const file = input.files[0];
    if (!file) return;

    const { extensions, message } = ACCEPTED_EXTENSIONS[input.id];
    const lower = file.name.toLowerCase();
    if (!extensions.some(extension => lower.endsWith(extension))) {
        showAlert(message, 'warning');
        input.value = '';
        return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
        showAlert('File size too large. Maximum size is 100MB', 'warning');
        input.value = '';
        return;
    }

    const existingInfo = input.parentNode.querySelector('small.text-muted');
    if (existingInfo && existingInfo.textContent.startsWith('Selected:')) {
        existingInfo.remove();
    }
    const fileInfo = document.createElement('small');
    fileInfo.className = 'text-muted d-block mt-1';
    fileInfo.textContent = `Selected: ${file.name} (${formatFileSize(file.size)})`;
    input.parentNode.appendChild(fileInfo);
}

// Offer the columns of the log in each mapping select, with the likely one
// already chosen. A column nothing looks like is never taken from the first
// one in the list: an optional role is left out ("(none)"), a required one
// has to be chosen before the form can be sent.
function populateCsvMapping(headers) {
    const guesses = guessColumnMapping(headers);
    for (const [role, selectId] of Object.entries(CSV_MAPPING_SELECTS)) {
        const select = byId(selectId);
        if (!select) continue;
        const optional = OPTIONAL_ROLES.includes(role);
        const empty = new Option(optional ? '(none)' : 'Choose a column...', '');
        empty.disabled = !optional;
        select.replaceChildren(empty, ...headers.map(header => new Option(header, header)));
        select.required = !optional;
        select.value = guesses[role] || '';
    }
}

function clearCsvMapping() {
    for (const selectId of Object.values(CSV_MAPPING_SELECTS)) {
        const select = byId(selectId);
        if (!select) continue;
        select.replaceChildren();
        select.required = false;
    }
}

// When a log is picked, read its beginning to learn the names of its columns
// and show the mapping.
function handleEventLogFileChange(event) {
    const file = event.target.files && event.target.files[0];
    const mappingDiv = byId('csvColumnMapping');
    if (!mappingDiv) return;

    const lowerName = file ? file.name.toLowerCase() : '';
    if (!file || !(lowerName.endsWith('.csv') || lowerName.endsWith('.xes'))) {
        mappingDiv.style.display = 'none';
        clearCsvMapping();
        return;
    }

    const isCsv = lowerName.endsWith('.csv');
    const slice = file.slice(0, isCsv ? 64 * 1024 : 256 * 1024);
    const reader = new FileReader();
    reader.onload = (e) => {
        const text = String(e.target.result || '');
        let headers;
        if (isCsv) {
            const firstLine = text.split(/\r?\n/, 1)[0];
            if (!firstLine) {
                showAlert('Could not read CSV header', 'warning');
                return;
            }
            headers = parseCsvHeaderLine(firstLine);
        } else {
            headers = extractXesColumns(text);
            if (headers.length === 0) {
                showAlert('Could not extract columns from XES file', 'warning');
                return;
            }
        }
        populateCsvMapping(headers);
        mappingDiv.style.display = 'block';
    };
    reader.onerror = () => showAlert('Failed to read event log file', 'danger');
    reader.readAsText(slice);
}

// While the discovery runs, show under the spinner which step it is at.
function startDiscoveryProgressPolling(sessionId) {
    const tick = async () => {
        try {
            const body = await getJson(`/api/discover/${sessionId}/progress`);
            if (body.in_progress && body.message) {
                updateLoadingMessage('Discovering parameters...', body.message);
            }
        } catch (e) {
            // Only a progress report: the discovery itself is still running.
        }
    };
    tick();
    return setInterval(tick, 1500);
}

function discoveryOptions() {
    const value = (id, fallback) => (byId(id) && byId(id).value) || fallback;
    const flag = (id) => (byId(id) && byId(id).checked ? '1' : '0');
    return new URLSearchParams({
        max_depth_tree: value('maxDepthTree', '0'),
        incremental_discovery: flag('incrementalDiscoveryToggle'),
        grace_period: value('gracePeriod', '1000'),
        enable_multitasking: flag('enableMultitaskingToggle'),
        multitasking_thr: value('multitaskingThr', '0.05'),
        random_state: value('randomState', '72'),
        use_workload_features: flag('useWorkloadFeaturesToggle'),
        attribute_mode: value('attributeMode', 'distribution'),
    });
}

async function handleUpload(event) {
    event.preventDefault();
    const formData = new FormData(event.target);

    showLoading('Uploading file...', 'Discovering process model and parameters');
    try {
        const uploadResult = await request('/api/upload', { method: 'POST', form: formData });
        showAlert('File uploaded successfully', 'success');

        updateLoadingMessage('Discovering parameters...', 'Preparing discovery...');
        const progressTimer = startDiscoveryProgressPolling(uploadResult.session_id);
        let discoverResult;
        try {
            discoverResult = await request(
                `/api/discover/${uploadResult.session_id}?${discoveryOptions().toString()}`, { method: 'POST' },
            );
        } finally {
            clearInterval(progressTimer);
        }

        hideLoading();
        showAlert('Parameters discovered successfully', 'success');
        // What the discovery found worth knowing (activities nobody performs
        // in the log, missing timestamps...). It changes how the simulation
        // behaves, so it stays on screen longer than the success message.
        (discoverResult.warnings || []).forEach(warning => showAlert(warning, 'warning', 15000));

        // Whether the accuracy metrics were asked for decides if their card
        // appears at all.
        const computeEvalToggle = byId('computeEvaluationToggle');
        const computeEval = !!(computeEvalToggle && computeEvalToggle.checked);
        // A new session: its scenarios are not known yet.
        state.runs = [];
        state.activeRunId = null;
        await loadSessionData(uploadResult.session_id, discoverResult.parameters, computeEval);
    } catch (error) {
        hideLoading();
        // A discovery error says what to fix in the log: it stays until closed.
        showAlert(`Error: ${error.message}`, 'danger', 0);
        // The log may have been stored before the failure: it is in the list.
        refreshSessionsList();
    }
}

/** Wire the upload form: source of the Petri net, discovery options, file checks, submission. */
export function initUploadForm() {
    showSliderValue('noiseThreshold', 'thresholdValue');
    initPetriNetSource();
    initIncrementalDiscovery();
    initMultitasking();

    const uploadForm = byId('uploadForm');
    if (uploadForm) {
        uploadForm.addEventListener('submit', handleUpload);
        // A second click while the first submission starts must not send it twice.
        uploadForm.addEventListener('submit', () => {
            const submitBtn = uploadForm.querySelector('button[type="submit"]');
            if (!submitBtn) return;
            submitBtn.disabled = true;
            setTimeout(() => { submitBtn.disabled = false; }, 2000);
        });
    }

    const fileInput = byId('xesFile');
    if (fileInput) fileInput.addEventListener('change', handleEventLogFileChange);

    for (const id of Object.keys(ACCEPTED_EXTENSIONS)) {
        const input = byId(id);
        if (input) input.addEventListener('change', () => checkPickedFile(input));
    }
}
