/**
 * Results: distribution of the case durations.
 */

import { on } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { TIME_UNIT_LABELS, getResultsTimeUnit, loadResult, renderHistogramResult } from './common.js';

export function loadCaseDuration() {
    const unit = getResultsTimeUnit('caseDurationUnit');
    const container = document.getElementById('caseDurationDist');
    return loadResult(
        container, 'case durations',
        `/api/get_visualization/${state.sessionId}/case_duration_dist?unit=${encodeURIComponent(unit)}`,
        (result) => {
            const unitLabel = TIME_UNIT_LABELS[result.unit || unit] || 'min';
            const m = result.metrics || {};
            renderHistogramResult(container, 'caseDurationCanvas', result, {
                metrics: {
                    mean: m.average_case_duration || 0,
                    median: m.median_case_duration || 0,
                    min: m.min_case_duration || 0,
                    max: m.max_case_duration || 0,
                },
                unitLabel,
                xLabel: `Case duration (${unitLabel})`,
                title: 'Case Duration Distribution',
            });
        },
    );
}

on('change', { 'reload-case-duration': () => loadCaseDuration() });
