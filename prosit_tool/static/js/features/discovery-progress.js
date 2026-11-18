/**
 * How far a discovery has got, shown in the loading dialog while it runs.
 *
 * The server knows which step the discovery is at and how far that step is
 * (GET /api/discover/<id>/progress); the page asks twice a second.
 */

import { getJson } from '../core/api.js';
import { formatDuration } from '../core/format.js';
import { setLoadingProgress, updateLoadingMessage } from '../core/ui.js';

const ASK_EVERY_MS = 500;

const counted = (number) => Number(number).toLocaleString('en-US');

/**
 * What the dialog shows for a `report` of the server, `elapsedSeconds` after
 * the discovery was asked for. Until the first report arrives (`null`) there
 * is only the time that has passed.
 */
export function describeProgress(report, elapsedSeconds) {
    const shown = {
        label: 'Preparing the discovery...',
        percent: 0,
        percentText: '0%',
        step: '',
        count: '',
        elapsed: `${formatDuration(elapsedSeconds)} elapsed`,
    };
    if (!report) return shown;

    if (report.label) shown.label = `${report.label}...`;
    shown.percent = Math.min(100, Math.max(0, Number(report.percent) || 0));
    shown.percentText = `${Math.floor(shown.percent)}%`;
    if (report.steps) shown.step = `Step ${report.step} of ${report.steps}`;
    if (report.total) {
        const unit = report.unit ? ` ${report.unit}` : '';
        shown.count = `${counted(report.done)} of ${counted(report.total)}${unit}`;
    }
    return shown;
}

/**
 * Keep the loading dialog up to date on the discovery of a session, until
 * `stop()` is called on what is returned.
 */
export function watchDiscoveryProgress(sessionId, title = 'Discovering parameters...') {
    const startedAt = performance.now();
    let report = null;
    let asking = false;
    let stopped = false;

    const show = () => {
        if (stopped) return;
        const shown = describeProgress(report, (performance.now() - startedAt) / 1000);
        updateLoadingMessage(title, shown.label);
        setLoadingProgress(shown);
    };

    const ask = async () => {
        if (asking) return;   // the answer to the last question is still on its way
        asking = true;
        try {
            const answer = await getJson(`/api/discover/${sessionId}/progress`);
            if (answer.in_progress) report = answer;
        } catch (error) {
            // Only a report is missing: the discovery itself is still running.
        } finally {
            asking = false;
        }
        show();
    };

    const tick = () => {
        show();   // the clock runs even while an answer is late
        ask();
    };
    tick();
    const timer = setInterval(tick, ASK_EVERY_MS);

    return {
        stop() {
            stopped = true;
            clearInterval(timer);
        },
    };
}
