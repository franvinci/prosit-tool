/**
 * The Simulation Results card: which chart loads when.
 *
 * The process map and the case durations load with the card. The other tabs
 * load the first time they are opened after a simulation, so that charts
 * nobody looks at cost nothing.
 */

import { getJson } from '../../core/api.js';
import { state } from '../../core/state.js';
import { loadActivityDuration } from './activity-duration.js';
import { loadCaseDuration } from './case-duration.js';
import { withRunId } from './common.js';
import { loadProcessMap } from './process-map.js';
import { loadResourceHeatmap } from './resource-heatmap.js';
import { loadWaitingTime } from './waiting-time.js';

const LAZY_TABS = {
    'resource-utilization-tab': loadResourceHeatmap,
    'activity-duration-tab': loadActivityDuration,
    'waiting-time-tab': loadWaitingTime,
};

/** Load a lazy tab when it is opened, once per simulation. */
export function initResults() {
    for (const [tabId, load] of Object.entries(LAZY_TABS)) {
        const tab = document.getElementById(tabId);
        if (!tab) continue;
        tab.addEventListener('shown.bs.tab', () => {
            if (tab.dataset.loaded) return;
            tab.dataset.loaded = '1';
            load();
        });
    }
}

function fillSelect(id, anyLabel, names) {
    const select = document.getElementById(id);
    if (!select) return;
    select.replaceChildren(new Option(anyLabel, ''), ...names.map(name => new Option(name, name)));
}

// The filters of the lazy tabs list the activities and resources of the
// simulated log.
async function populateFilters() {
    try {
        const result = await getJson(withRunId(`/api/get_activities_and_resources/${state.sessionId}`));
        fillSelect('activitySelect', 'Any activity', result.activities);
        fillSelect('waitingTimeSelect_res', 'Any resource', result.resources);
        fillSelect('waitingTimeSelect_act', 'Any activity', result.activities);
        fillSelect('resourceHeatmapSelect', 'Any resource', result.resources);
    } catch (error) {
        console.error('Error populating dropdowns:', error);
    }
}

/** Show the results of the scenario on screen. */
export async function loadAllVisualizations() {
    const controls = document.getElementById('processMapControls');
    if (controls) controls.style.display = '';

    await loadProcessMap();
    await loadCaseDuration();
    // The filters first: the lazy tabs read them when they load.
    await populateFilters();

    for (const [tabId, load] of Object.entries(LAZY_TABS)) {
        const tab = document.getElementById(tabId);
        if (!tab) continue;
        if (tab.classList.contains('active')) {
            // Already open: nothing will announce it, so load it now.
            tab.dataset.loaded = '1';
            load();
        } else {
            delete tab.dataset.loaded;
        }
    }
}
