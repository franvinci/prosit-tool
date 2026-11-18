/**
 * Results: distribution of the waiting times, by resource and by activity.
 */

import { on } from '../../core/dom.js';
import { state } from '../../core/state.js';
import { TIME_UNIT_LABELS, getResultsTimeUnit, loadResult, renderHistogramResult } from './common.js';

export function loadWaitingTime() {
    if (!state.sessionId) return Promise.resolve();
    const resourceSelect = document.getElementById('waitingTimeSelect_res');
    const activitySelect = document.getElementById('waitingTimeSelect_act');
    const resource = resourceSelect ? resourceSelect.value : '';
    const activity = activitySelect ? activitySelect.value : '';
    const unit = getResultsTimeUnit('waitingTimeUnit');
    const params = new URLSearchParams();
    if (activity) params.append('activity', activity);
    if (resource) params.append('resource', resource);
    params.append('unit', unit);

    const container = document.getElementById('waitingTimeVisualizationContainer');
    return loadResult(
        container, 'waiting time',
        `/api/get_visualization/${state.sessionId}/waiting_time_dist?${params.toString()}`,
        (result) => {
            const unitLabel = TIME_UNIT_LABELS[result.unit || unit] || 'min';
            const m = result.metrics || {};
            const about = [
                result.resource ? `Resource: ${result.resource}` : 'Resource: Any',
                result.activity ? `Activity: ${result.activity}` : 'Activity: Any',
            ];
            renderHistogramResult(container, 'waitingTimeCanvas', result, {
                metrics: {
                    mean: m.average_duration || 0,
                    median: m.median_duration || 0,
                    min: m.min_duration || 0,
                    max: m.max_duration || 0,
                },
                unitLabel,
                xLabel: `Waiting time (${unitLabel})`,
                title: `Waiting Time — ${about.join(' · ')}`,
            });
        },
    );
}

on('change', { 'reload-waiting-time': () => loadWaitingTime() });
