/**
 * Results: distribution of the durations of one activity, or of all of them.
 */

import { on } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { TIME_UNIT_LABELS, getResultsTimeUnit, loadResult, renderHistogramResult } from './common.js';

export function loadActivityDuration() {
    if (!state.sessionId) return Promise.resolve();
    const select = document.getElementById('activitySelect');
    const activityName = select ? select.value : '';
    const unit = getResultsTimeUnit('activityDurationUnit');
    const params = new URLSearchParams();
    if (activityName) params.append('activity', activityName);
    params.append('unit', unit);

    const container = document.getElementById('activityDurationBoxplotContainer');
    return loadResult(
        container, 'activity duration',
        `/api/get_visualization/${state.sessionId}/activity_duration_boxplot?${params.toString()}`,
        (result) => {
            const unitLabel = TIME_UNIT_LABELS[result.unit || unit] || 'min';
            const m = result.metrics || {};
            renderHistogramResult(container, 'activityDurationCanvas', result, {
                metrics: {
                    mean: m.average_duration || 0,
                    median: m.median_duration || 0,
                    min: m.min_duration || 0,
                    max: m.max_duration || 0,
                },
                unitLabel,
                xLabel: `Duration (${unitLabel})`,
                title: result.activity ? `Activity Duration — ${result.activity}` : 'Activity Duration — All activities',
            });
        },
    );
}

on('change', { 'reload-activity-duration': () => loadActivityDuration() });
