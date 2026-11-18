/**
 * The parameters card: the drawing of the net and one tab per group of
 * parameters.
 */

import { state } from '../../core/state.js';
import { renderPetriNet } from '../petri-net.js';
import { renderAccuracyResults } from '../results/accuracy.js';
import { renderInterArrivalTimeParameters } from './arrival.js';
import { renderDataAttributeParameters } from './attributes.js';
import { renderExecutionTimeParameters } from './execution.js';
import { renderResourceParameters } from './resources.js';
import { renderTransitionParameters } from './transitions.js';
import { renderWaitingTimeParameters } from './waiting.js';

/** Show a whole set of parameters: called when a session or a scenario is opened. */
export function renderParameters(parameters) {
    renderPetriNet(parameters.process_model);
    renderTransitionParameters(parameters.transition_params);
    renderResourceParameters(parameters.resource_params);
    renderExecutionTimeParameters(parameters.execution_time_params);
    renderWaitingTimeParameters();
    renderInterArrivalTimeParameters(parameters.inter_arrival_params || {});
    renderDataAttributeParameters(parameters.data_attribute_params || {});

    // The accuracy card appears only if the metrics exist or were asked for.
    const wantsMetrics = !!(parameters && parameters._compute_evaluation_requested);
    renderAccuracyResults(parameters.prosit_metrics || {}, state.sessionId, wantsMetrics);
}
