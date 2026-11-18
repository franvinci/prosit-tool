/**
 * Entry point of the page: loads every feature and starts the ones that have
 * something to set up. Most features only need to be loaded: they handle the
 * elements marked data-action="..." wherever those appear.
 */

import { initTooltipsIn, patchFeatherReplace } from './core/dom.js';
import { initResults } from './features/results/index.js';
import { initSimulationControls } from './features/simulation.js';
import { initUploadForm } from './features/upload.js';
import './features/params/tree-splits.js';

patchFeatherReplace();
initUploadForm();
initSimulationControls();
initResults();
feather.replace();
initTooltipsIn(document);
