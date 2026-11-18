import assert from 'node:assert/strict';
import { afterEach, beforeEach, mock, test } from 'node:test';

import { formatDuration } from '../../prosit_tool/static/js/core/format.js';
import { setLoadingProgress, updateLoadingMessage } from '../../prosit_tool/static/js/core/ui.js';
import { describeProgress, watchDiscoveryProgress } from '../../prosit_tool/static/js/features/discovery-progress.js';

// ---- the loading dialog of the page, as far as these modules touch it ------------------------

const elements = {};

function element(id) {
    if (!elements[id]) {
        const classes = new Set(['d-none']);
        elements[id] = {
            textContent: '',
            style: {},
            attributes: {},
            setAttribute(name, value) { this.attributes[name] = value; },
            classList: {
                toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
                contains: (name) => classes.has(name),
            },
        };
    }
    return elements[id];
}

globalThis.document = { getElementById: element };

const text = (id) => element(id).textContent;
// Let the answer of a (fake) request reach the code that waits for it.
const settle = () => new Promise((resolve) => setImmediate(resolve));

const REPORT = {
    in_progress: true, percent: 41.7, step: 3, steps: 15,
    label: 'Measuring the fitness of the model', done: 1234, total: 5678, unit: 'variants', elapsed: 12.3,
};

beforeEach(() => {
    for (const id of Object.keys(elements)) delete elements[id];
});

afterEach(() => {
    mock.timers.reset();
    delete globalThis.fetch;
});

// ---- time ------------------------------------------------------------------------------------

test('a length of time reads like a stopwatch', () => {
    assert.equal(formatDuration(0), '0:00');
    assert.equal(formatDuration(7.9), '0:07');
    assert.equal(formatDuration(65), '1:05');
    assert.equal(formatDuration(725), '12:05');
    assert.equal(formatDuration(3725), '1:02:05');
});

test('a length of time that makes no sense reads as none', () => {
    assert.equal(formatDuration(-3), '0:00');
    assert.equal(formatDuration(undefined), '0:00');
    assert.equal(formatDuration('soon'), '0:00');
});

// ---- what the dialog says ------------------------------------------------------------------------

test('before the first report there is only the time that has passed', () => {
    assert.deepEqual(describeProgress(null, 2.4), {
        label: 'Preparing the discovery...', percent: 0, percentText: '0%', step: '', count: '', elapsed: '0:02 elapsed',
    });
});

test('a report says the step, how far it is and what it counts', () => {
    assert.deepEqual(describeProgress(REPORT, 83), {
        label: 'Measuring the fitness of the model...',
        percent: 41.7,
        percentText: '41%',
        step: 'Step 3 of 15',
        count: '1,234 of 5,678 variants',
        elapsed: '1:23 elapsed',
    });
});

test('a step that counts nothing shows no count', () => {
    const { done, total, unit, ...report } = REPORT;
    assert.equal(describeProgress(report, 1).count, '');
    assert.equal(describeProgress({ ...report, done: 3, total: 9 }, 1).count, '3 of 9');
});

test('the time shown is the one of the page, not the one in the report', () => {
    assert.equal(describeProgress({ ...REPORT, elapsed: 999 }, 5).elapsed, '0:05 elapsed');
});

test('a percentage out of range does not leave the bar', () => {
    assert.equal(describeProgress({ ...REPORT, percent: 140 }, 0).percent, 100);
    assert.equal(describeProgress({ ...REPORT, percent: -5 }, 0).percentText, '0%');
    assert.equal(describeProgress({ ...REPORT, percent: 'half' }, 0).percent, 0);
    // never "100%" while the work is still going on
    assert.equal(describeProgress({ ...REPORT, percent: 99.9 }, 0).percentText, '99%');
});

// ---- the bar in the dialog -----------------------------------------------------------------------

test('the bar is filled and its texts written', () => {
    setLoadingProgress(describeProgress(REPORT, 83));

    assert.equal(element('loadingProgress').classList.contains('d-none'), false);
    assert.equal(element('loadingProgressBar').style.width, '41.7%');
    assert.equal(element('loadingProgressTrack').attributes['aria-valuenow'], '41');
    assert.equal(text('loadingProgressStep'), 'Step 3 of 15');
    assert.equal(text('loadingProgressPercent'), '41%');
    assert.equal(text('loadingProgressCount'), '1,234 of 5,678 variants');
    assert.equal(text('loadingProgressElapsed'), '1:23 elapsed');
});

test('taking the bar away empties it for the next operation', () => {
    setLoadingProgress(describeProgress(REPORT, 83));

    setLoadingProgress(null);

    assert.equal(element('loadingProgress').classList.contains('d-none'), true);
    assert.equal(element('loadingProgressBar').style.width, '0%');
    assert.equal(text('loadingProgressStep') + text('loadingProgressPercent') + text('loadingProgressCount'), '');
});

test('a page without the dialog is left alone', () => {
    const page = globalThis.document;
    globalThis.document = { getElementById: () => null };
    try {
        setLoadingProgress(describeProgress(REPORT, 1));
        updateLoadingMessage('title', 'message');
    } finally {
        globalThis.document = page;
    }
});

// ---- following a discovery ------------------------------------------------------------------------

function serverSays(...answers) {
    const asked = [];
    globalThis.fetch = async (url) => {
        asked.push(url);
        const answer = answers[Math.min(asked.length, answers.length) - 1];
        if (answer instanceof Error) throw answer;
        return { ok: true, status: 200, json: async () => answer };
    };
    return asked;
}

test('the dialog shows the report of the server and keeps asking', async () => {
    mock.timers.enable({ apis: ['setInterval'] });
    const asked = serverSays(REPORT, { ...REPORT, percent: 60, step: 4, label: 'Measuring the precision of the model' });

    const watch = watchDiscoveryProgress(7);
    assert.equal(text('loadingMessage'), 'Discovering parameters...');
    assert.equal(text('loadingDetail'), 'Preparing the discovery...');     // at once, before any answer
    await settle();

    assert.deepEqual(asked, ['/api/discover/7/progress']);
    assert.equal(text('loadingDetail'), 'Measuring the fitness of the model...');
    assert.equal(element('loadingProgressBar').style.width, '41.7%');

    mock.timers.tick(500);
    await settle();
    assert.equal(asked.length, 2);
    assert.equal(text('loadingDetail'), 'Measuring the precision of the model...');
    assert.equal(text('loadingProgressStep'), 'Step 4 of 15');
    watch.stop();
});

test('nothing is asked or shown after it is stopped', async () => {
    mock.timers.enable({ apis: ['setInterval'] });
    const asked = serverSays(REPORT, { ...REPORT, percent: 90 });
    const watch = watchDiscoveryProgress(7);
    await settle();

    watch.stop();
    mock.timers.tick(5000);
    await settle();

    assert.equal(asked.length, 1);
    assert.equal(element('loadingProgressBar').style.width, '41.7%');
});

test('an answer that arrives after it is stopped is not shown', async () => {
    mock.timers.enable({ apis: ['setInterval'] });
    serverSays(REPORT);

    const watch = watchDiscoveryProgress(7);
    watch.stop();                      // the discovery ended while the first question was on its way
    await settle();

    assert.equal(text('loadingDetail'), 'Preparing the discovery...');
    assert.equal(element('loadingProgressBar').style.width, '0%');
});

test('a report that cannot be had leaves the last one on screen', async () => {
    mock.timers.enable({ apis: ['setInterval'] });
    const asked = serverSays(REPORT, new Error('network down'), { in_progress: false, message: '' });
    const watch = watchDiscoveryProgress(7);
    await settle();

    mock.timers.tick(500);      // the server cannot be reached
    await settle();
    mock.timers.tick(500);      // the discovery has just ended: nothing in progress
    await settle();

    assert.equal(asked.length, 3);
    assert.equal(text('loadingDetail'), 'Measuring the fitness of the model...');
    assert.equal(element('loadingProgressBar').style.width, '41.7%');
    watch.stop();
});

test('a slow answer is waited for, not asked for again', async () => {
    mock.timers.enable({ apis: ['setInterval'] });
    let answer;
    let asked = 0;
    globalThis.fetch = () => {
        asked += 1;
        return new Promise((resolve) => { answer = () => resolve({ ok: true, status: 200, json: async () => REPORT }); });
    };

    const watch = watchDiscoveryProgress(7);
    mock.timers.tick(500);
    mock.timers.tick(500);
    await settle();
    assert.equal(asked, 1);

    answer();
    await settle();
    mock.timers.tick(500);
    await settle();
    assert.equal(asked, 2);
    watch.stop();
});
