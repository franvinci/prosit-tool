import assert from 'node:assert/strict';
import { test } from 'node:test';

// The editor registers its actions on the document as soon as it is loaded.
const listeners = {};
globalThis.Element = class {};
globalThis.document = { addEventListener: (type, listener) => { listeners[type] = listener; } };
const { registerDistributionKind, renderDistributionParameters, renderFamilySelect } =
    await import('../../prosit_tool/static/js/features/params/distribution-editor.js');

const fieldsOf = (html) => [...html.matchAll(/value="([^"]*)"(?: placeholder="auto")?\s+data-action="set-distribution-param" data-param="(\w+)"/g)]
    .map(match => [match[2], match[1]]);

test('each family shows its own fields, with the values of the entry', () => {
    assert.deepEqual(fieldsOf(renderDistributionParameters('execution', 'A', 'norm', { mean: 12, std: 3, min: 1, max: 40 })),
        [['mean', '12'], ['std', '3'], ['min', '1'], ['max', '40']]);
    assert.deepEqual(fieldsOf(renderDistributionParameters('execution', 'A', 'fixed', { value: 7 })), [['value', '7']]);
    assert.deepEqual(fieldsOf(renderDistributionParameters('execution', 'A', 'uniform', { min: 2, max: 9 })), [['min', '2'], ['max', '9']]);
    assert.deepEqual(fieldsOf(renderDistributionParameters('execution', 'A', 'lognorm', { shape: 0.4, loc: 1, scale: 20, min: 0, max: 99 })),
        [['scale', '20'], ['shape', '0.4'], ['loc', '1'], ['min', '0'], ['max', '99']]);
});

test('what the server sent is shown until the user edits it', () => {
    const fromServer = { mean: 15, std: 5, min_value: 2, max_value: 60, mean_value: 15 };
    assert.deepEqual(fieldsOf(renderDistributionParameters('waiting', 'r', 'norm', fromServer)),
        [['mean', '15'], ['std', '5'], ['min', '2'], ['max', '60']]);
    const edited = { ...fromServer, min: 0, max: 30 };
    assert.deepEqual(fieldsOf(renderDistributionParameters('waiting', 'r', 'norm', edited)),
        [['mean', '15'], ['std', '5'], ['min', '0'], ['max', '30']]);
});

test('a bound that is not set is shown as automatic, not as a number nobody chose', () => {
    const html = renderDistributionParameters('execution', 'A', 'expon', { mean: 120 });
    assert.deepEqual(fieldsOf(html), [['mean', '120'], ['min', ''], ['max', '']]);
    assert.equal(html.split('placeholder="auto"').length - 1, 2);
    // the two ends of a uniform are the distribution: they always have a value
    assert.ok(!renderDistributionParameters('execution', 'A', 'uniform', { min: 2, max: 9 }).includes('placeholder'));
});

test('a gamma is shown as mean and standard deviation, whichever way it is stored', () => {
    const fields = Object.fromEntries(fieldsOf(renderDistributionParameters('execution', 'A', 'gamma', { shape: 4, scale: 3, min_value: 0, max_value: 50 })));
    assert.equal(fields.mean, '12');
    assert.equal(fields.std, '6');
    const edited = Object.fromEntries(fieldsOf(renderDistributionParameters('execution', 'A', 'gamma', { mean: 20, std: 2, shape: 4, scale: 3 })));
    assert.equal(edited.mean, '20');
    assert.equal(edited.std, '2');
});

test('an unknown family has no fields', () => {
    assert.equal(renderDistributionParameters('execution', 'A', 'weibull', { a: 1 }), '');
});

test('the name of the entry is carried as data, whatever characters it has', () => {
    const name = `O'Neil's "review" <b>&`;
    const html = renderDistributionParameters('execution', name, 'fixed', { value: 1 }) + renderFamilySelect('execution', name, 'fixed');
    assert.ok(!html.includes('<b>'));
    assert.equal(html.split('data-item="O&#39;Neil&#39;s &quot;review&quot; &lt;b&gt;&amp;"').length - 1, 2);
    assert.ok(!/\bon[a-z]+=/.test(html), 'no inline handler');
});

test('the select of the family offers every family and marks the current one', () => {
    const html = renderFamilySelect('arrival', 'inter_arrival_time', 'gamma');
    assert.deepEqual([...html.matchAll(/<option value="(\w+)"( selected)?>/g)].map(m => m[1] + (m[2] ? '*' : '')),
        ['fixed', 'norm', 'expon', 'uniform', 'lognorm', 'gamma*']);
});

function field(action, dataset, value) {
    const element = new globalThis.Element();
    Object.assign(element, { dataset: { action, ...dataset }, value, closest() { return this; } });
    return element;
}

test('an edit reaches the tab the entry belongs to', () => {
    const seen = [];
    registerDistributionKind('test-kind', {
        update: (item, param, value) => seen.push(['update', item, param, value]),
        refresh: (item) => seen.push(['refresh', item]),
    });
    listeners.change({ type: 'change', target: field('set-distribution-param', { kind: 'test-kind', item: 'A', param: 'mean' }, '12.5') });
    listeners.change({ type: 'change', target: field('set-distribution-family', { kind: 'test-kind', item: 'A' }, 'uniform') });
    assert.deepEqual(seen, [
        ['update', 'A', 'mean', 12.5],
        ['update', 'A', 'distribution', 'uniform'],
        ['refresh', 'A'],
    ]);
});
