import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

import { ApiError, getJson, postJson, request } from '../../prosit_tool/static/js/core/api.js';
import { escapeHtml, infoIcon, on } from '../../prosit_tool/static/js/core/dom.js';
import { formatDateTime, formatFileSize } from '../../prosit_tool/static/js/core/format.js';
import {
    EDITABLE_SECTIONS, activeRun, clearParametersDirty, editableParameters, isBaselineActive, markParametersDirty,
    onDirtyChange, state,
} from '../../prosit_tool/static/js/core/state.js';

// ---- escaping ----------------------------------------------------------------------------

test('escapeHtml makes a name safe as text and inside a quoted attribute', () => {
    assert.equal(escapeHtml(`O'Brien "Jr" <b>&`), 'O&#39;Brien &quot;Jr&quot; &lt;b&gt;&amp;');
    assert.equal(escapeHtml('plain'), 'plain');
    assert.equal(escapeHtml(0), '0');
});

test('escapeHtml shows nothing for a missing value', () => {
    assert.equal(escapeHtml(null), '');
    assert.equal(escapeHtml(undefined), '');
});

test('the text of an info icon cannot break out of its attribute', () => {
    const html = infoIcon('5" > 3 & "quoted"');
    assert.ok(html.includes('title="5&quot; &gt; 3 &amp; &quot;quoted&quot;"'), html);
});

// ---- delegated events ------------------------------------------------------------------------

class FakeElement {
    constructor(action, parent = null) {
        this.dataset = action ? { action } : {};
        this.parent = parent;
    }
    closest() {
        for (let element = this; element; element = element.parent) {
            if (element.dataset.action) return element;
        }
        return null;
    }
}

// One page for the whole file: `on` adds its listener to the document the
// first time an event type is used, and keeps it.
const listeners = {};
globalThis.Element = FakeElement;
globalThis.document = { addEventListener: (type, listener) => { (listeners[type] ||= []).push(listener); } };
const dispatch = (type, target) => (listeners[type] || []).forEach(listener => listener({ type, target }));

afterEach(() => {
    delete globalThis.fetch;
});

test('an action runs for the marked element, whichever child was clicked', () => {
    const seen = [];
    on('click', { 'test-open': (element, event) => seen.push([element, event.type]) });
    const row = new FakeElement('test-open');
    dispatch('click', new FakeElement(null, new FakeElement(null, row)));
    assert.deepEqual(seen, [[row, 'click']]);
});

test('the innermost marked element wins: a button in a row does not open the row', () => {
    const seen = [];
    on('click', { 'test-row': () => seen.push('row'), 'test-delete': () => seen.push('delete') });
    const row = new FakeElement('test-row');
    dispatch('click', new FakeElement(null, new FakeElement('test-delete', row)));
    assert.deepEqual(seen, ['delete']);
});

test('an action is handled only for the events it was registered for', () => {
    const seen = [];
    on('change', { 'test-pick': () => seen.push('change') });
    on('click', { 'test-other': () => seen.push('click') });
    const select = new FakeElement('test-pick');
    dispatch('click', select);
    assert.deepEqual(seen, []);
    dispatch('change', select);
    assert.deepEqual(seen, ['change']);
    dispatch('click', new FakeElement(null));
    assert.deepEqual(seen, ['change']);
});

test('two handlers for the same action are a mistake, reported at once', () => {
    on('click', { 'test-twice': () => {} });
    assert.throws(() => on('click', { 'test-twice': () => {} }), /already handled/);
});

// ---- calls to the server ------------------------------------------------------------------------

function answer(status, body, { json = true } = {}) {
    const calls = [];
    globalThis.fetch = async (url, options) => {
        calls.push({ url, options });
        return {
            ok: status >= 200 && status < 300,
            status,
            json: async () => { if (!json) throw new SyntaxError('not JSON'); return body; },
        };
    };
    return calls;
}

test('a good answer is returned as it is', async () => {
    const calls = answer(200, { success: true, runs: [1, 2] });
    assert.deepEqual(await getJson('/api/sessions/1/runs'), { success: true, runs: [1, 2] });
    assert.deepEqual(calls, [{ url: '/api/sessions/1/runs', options: { method: 'GET' } }]);
});

test('a JSON body is sent with its content type', async () => {
    const calls = answer(200, { success: true });
    await postJson('/api/simulate/3', { num_instances: 5 });
    assert.equal(calls[0].options.method, 'POST');
    assert.equal(calls[0].options.body, '{"num_instances":5}');
    assert.deepEqual(calls[0].options.headers, { 'Content-Type': 'application/json' });
});

test('a form is sent as it is, for the browser to encode', async () => {
    const calls = answer(200, { success: true });
    const form = { a: 'form' };
    await request('/api/upload', { method: 'POST', form });
    assert.equal(calls[0].options.body, form);
    assert.equal(calls[0].options.headers, undefined);
});

test('the reason the server gives becomes the message of the error', async () => {
    answer(400, { error: 'num_instances must be between 1 and 10000' });
    await assert.rejects(postJson('/api/simulate/3', {}), (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.message, 'num_instances must be between 1 and 10000');
        assert.equal(error.status, 400);
        return true;
    });
});

test('an unexpected failure carries the id to look for in the log', async () => {
    answer(500, { error: 'Simulation failed', error_id: 'a1b2c3' });
    await assert.rejects(getJson('/x'), { message: 'Simulation failed (error id a1b2c3)', status: 500 });
});

test('"success": false is a failure even with a 200', async () => {
    answer(200, { success: false, error: 'No simulation yet' });
    await assert.rejects(getJson('/x'), { message: 'No simulation yet' });
});

test('an answer that is not JSON is reported, not passed on', async () => {
    answer(502, null, { json: false });
    await assert.rejects(getJson('/x'), { message: 'The server answered with an error (502)', status: 502 });
    answer(200, null, { json: false });
    await assert.rejects(getJson('/x'), { message: 'The server sent an answer that cannot be read' });
});

test('a server that cannot be reached is an error with status 0', async () => {
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(getJson('/x'), (error) => error instanceof ApiError && error.status === 0 && /cannot be reached/.test(error.message));
});

// ---- state --------------------------------------------------------------------------------------

test('only what the editor changes is sent when a scenario is saved', () => {
    const parameters = {
        transition_params: { transition_weights: { t: 1 } },
        resource_params: { resources: [] },
        process_model: { visualization: '<svg/>' },
        prosit_metrics: { time: {} },
        _compute_evaluation_requested: true,
    };
    assert.deepEqual(editableParameters(parameters), {
        transition_params: { transition_weights: { t: 1 } },
        resource_params: { resources: [] },
    });
    assert.equal(editableParameters(parameters).transition_params, parameters.transition_params);
    assert.deepEqual(editableParameters(null), {});
    assert.equal(EDITABLE_SECTIONS.length, 6);
});

test('the scenario on screen is found among the scenarios of the session', () => {
    state.runs = [{ id: 1, is_baseline: true }, { id: 2, is_baseline: false }];
    state.activeRunId = 2;
    assert.equal(activeRun().id, 2);
    assert.equal(isBaselineActive(), false);
    state.activeRunId = 1;
    assert.equal(isBaselineActive(), true);
    state.activeRunId = null;
    assert.equal(activeRun(), null);
    assert.equal(isBaselineActive(), false);
    state.runs = [];
});

test('the first edit is announced once, saving always', () => {
    const seen = [];
    onDirtyChange(dirty => seen.push(dirty));
    clearParametersDirty();
    markParametersDirty();
    markParametersDirty();
    assert.equal(state.dirty, true);
    clearParametersDirty();
    assert.equal(state.dirty, false);
    assert.deepEqual(seen, [false, true, false]);
    onDirtyChange(() => {});
});

// ---- formatting -----------------------------------------------------------------------------------

test('a date and time is shown in the time of the person reading', () => {
    const local = new Date(2024, 2, 4, 9, 6);          // 4 March 2024, 09:06 here
    assert.equal(formatDateTime(local.toISOString()), '2024-03-04 09:06');
    assert.equal(formatDateTime(null), '');
    assert.equal(formatDateTime('not a date'), '');
});

test('file sizes are shown in the largest unit that fits', () => {
    assert.equal(formatFileSize(0), '0 Bytes');
    assert.equal(formatFileSize(512), '512 Bytes');
    assert.equal(formatFileSize(80461), '78.58 KB');
    assert.equal(formatFileSize(5 * 1024 * 1024), '5 MB');
});
