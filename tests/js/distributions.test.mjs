// Run with: node --test tests/js
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
    FAMILIES, TIME_FAMILY_DEFAULTS, distributionPdf, distributionRange, editTimeDistribution,
    leafParamsFromProsit, mergeDistParams,
} from '../../prosit_tool/static/js/features/params/distributions.js';

const close = (actual, expected, tolerance = 1e-9) => {
    assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not ${expected} (±${tolerance})`);
};

// ---- parameters of a tree leaf, from the list scipy fitted --------------------------

test('an exponential leaf shows its mean, shift included', () => {
    assert.deepEqual(leafParamsFromProsit('expon', [20, 14.6]), { loc: 20, mean: 34.6 });
    assert.deepEqual(leafParamsFromProsit('expon', [0, 30.5]), { loc: 0, mean: 30.5 });
});

test('a uniform leaf shows its two ends, not scipy\'s start and width', () => {
    assert.deepEqual(leafParamsFromProsit('uniform', [10, 20]), { min: 10, max: 30 });
});

test('a gamma leaf shows mean and standard deviation and keeps the shift', () => {
    const shown = leafParamsFromProsit('gamma', [4, -2, 3]);
    assert.equal(shown.loc, -2);
    close(shown.mean, -2 + 4 * 3);
    close(shown.std, Math.sqrt(4) * 3);
});

test('a fixed leaf shows the value of the leaf, which is what gets simulated', () => {
    assert.deepEqual(leafParamsFromProsit('fixed', [0.99514], { value: 0.995 }), { value: 0.995 });
    assert.deepEqual(leafParamsFromProsit('fixed', [7]), { value: 7 });
});

test('normal and log-normal leaves keep scipy\'s parameters under their names', () => {
    assert.deepEqual(leafParamsFromProsit('norm', [12, 3]), { mean: 12, std: 3 });
    assert.deepEqual(leafParamsFromProsit('lognorm', [0.4, 1, 20]), { shape: 0.4, loc: 1, scale: 20 });
});

test('parameters that are not a list are left to the caller', () => {
    assert.deepEqual(leafParamsFromProsit('norm', { mean: 1, std: 2 }), {});
    assert.deepEqual(leafParamsFromProsit('weibull', [1, 2]), {});
});

// ---- editing a time distribution ----------------------------------------------------

test('picking a family starts from its defaults, a copy of them', () => {
    const entry = { distribution: 'norm', parameters: { mean: 5, std: 1 } };
    editTimeDistribution(entry, 'distribution', 'uniform');
    assert.deepEqual(entry, { distribution: 'uniform', parameters: { min: 30, max: 240 } });
    entry.parameters.max = 1;
    assert.equal(TIME_FAMILY_DEFAULTS.uniform.max, 240);
});

test('every family an editor offers has defaults', () => {
    for (const [family] of FAMILIES) assert.ok(TIME_FAMILY_DEFAULTS[family], family);
});

test('editing a parameter touches only that parameter', () => {
    const entry = { distribution: 'norm', parameters: { mean: 5, std: 1 } };
    editTimeDistribution(entry, 'std', 2.5);
    assert.deepEqual(entry.parameters, { mean: 5, std: 2.5 });
});

test('a fixed value is its own minimum and maximum', () => {
    const entry = { distribution: 'fixed', parameters: { value: 1, min: 1, max: 1 } };
    editTimeDistribution(entry, 'value', 9);
    assert.deepEqual(entry.parameters, { value: 9, min: 9, max: 9 });
});

test('an entry without parameters gets them on the first edit', () => {
    const entry = {};
    editTimeDistribution(entry, 'mean', 3);
    assert.deepEqual(entry, { parameters: { mean: 3 } });
});

// ---- changing the family of a trace attribute -----------------------------------------

test('the typical value survives a change of family', () => {
    assert.equal(mergeDistParams({ value: 42, min: 42, max: 42 }, 'norm').mean, 42);
    assert.equal(mergeDistParams({ mean: 42, std: 3 }, 'lognorm').scale, 42);
});

test('what the families share is kept, the rest starts from the defaults', () => {
    assert.deepEqual(mergeDistParams({ mean: 42, std: 3, min: 1, max: 99 }, 'expon'), { mean: 42, min: 1, max: 99 });
    assert.deepEqual(mergeDistParams({ mean: 42 }, 'uniform'), { min: 0, max: 60 });
});

test('a fixed attribute has minimum and maximum equal to its value', () => {
    assert.deepEqual(mergeDistParams({ mean: 8, std: 2, min: 0, max: 60 }, 'fixed'), { value: 8, min: 8, max: 8 });
});

// ---- densities drawn in the previews -----------------------------------------------------

function integral(family, params, from, to, steps = 20000) {
    const width = (to - from) / steps;
    let sum = 0;
    for (let i = 0; i < steps; i++) sum += distributionPdf(family, params, from + (i + 0.5) * width) * width;
    return sum;
}

test('each density has area one', () => {
    close(integral('norm', { mean: 10, std: 2 }, -10, 30), 1, 1e-6);
    close(integral('expon', { mean: 5 }, 0, 200), 1, 1e-4);
    close(integral('uniform', { min: 2, max: 6 }, 0, 8), 1, 1e-3);
    close(integral('lognorm', { shape: 0.5, loc: 0, scale: 10 }, 0, 400), 1, 1e-4);
    close(integral('gamma', { mean: 12, std: 4 }, 0, 200), 1, 1e-4);
});

test('a shifted exponential starts at its shift and keeps its mean', () => {
    const params = { loc: 20, mean: 34.6 };
    assert.equal(distributionPdf('expon', params, 19.9), 0);
    close(integral('expon', params, 20, 600), 1, 1e-4);
    const [from, to] = distributionRange('expon', params);
    assert.equal(from, 20);
    assert.ok(to > 34.6);
});

test('a shifted gamma is drawn where its density is', () => {
    // large shape, large negative shift: what scipy fits to a bell-shaped sample
    const params = { loc: -313, mean: 17.2, std: 8.07 };
    close(integral('gamma', params, -313, 200), 1, 1e-3);
    const [from, to] = distributionRange('gamma', params);
    assert.ok(from > -30 && from < 17.2, `range starts at ${from}`);
    assert.ok(to > 17.2 + 3 * 8.07);
});

test('an unknown family has no preview', () => {
    assert.equal(distributionRange('weibull', {}), null);
    assert.equal(distributionPdf('weibull', {}, 1), null);
});
