/**
 * Decision trees in the parameters: telling whether a session uses them, and
 * the tree a new entry starts with.
 *
 * A tree is an object keyed by node id, the root being "0". A session
 * discovered with rules has trees everywhere a plain value would be.
 */

import { state } from '../../core/state.js';

/** True when `value` is a tree and not a plain number or distribution. */
export function isTree(value) {
    return !!value && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, '0');
}

export function isDecisionTreeModeForResourceWeights() {
    const weights = state.parameters?.resource_params?.resource_weights || {};
    return Object.values(weights).some(isTree);
}

export function isDecisionTreeModeForWaitingTimes() {
    const waits = state.parameters?.waiting_time_params?.resource_waiting_times || {};
    return Object.values(waits).some(isTree);
}

/** A tree with a single leaf: an exponential time with the given mean (minutes). */
export function singleLeafTimeTree(mean = 15) {
    return {
        '0': {
            'value': mean,
            'dist': {
                'dist_name': 'expon',
                'params': { 'mean': mean },
                'min_value': 0.0,
                'max_value': 100.0
            }
        }
    };
}

/**
 * True for a feature that is a condition ("kind = gold", "resource = Anna")
 * and not a number compared with a threshold ("hour", a count of activities).
 */
export function isCategoricalFeature(feature) {
    return String(feature).includes(' = ');
}

/**
 * Ids of the two children of a split as prosit-pm follows them:
 * `[taken when feature <= threshold, taken otherwise]`. It names the branches
 * "true"/"false" in memory and "1"/"0" once the tree has been through JSON.
 */
export function branchIds(children) {
    return [
        children.true ?? children['1'] ?? children.True,
        children.false ?? children['0'] ?? children.False,
    ];
}

/**
 * Ids of the two children of a split as the editor shows them:
 * `[when the condition on screen holds, when it does not]`.
 *
 * For a number the condition on screen is the test prosit-pm makes
 * ("hour ≤ 17.5"). A condition such as "kind = gold" is a feature worth 1
 * when it holds and 0 when it does not, split at 0.5: prosit-pm's "true"
 * branch (feature <= 0.5) is then the one of the cases where the condition
 * does NOT hold, so the two are swapped.
 */
export function shownBranches(node) {
    const [atMost, above] = branchIds(node.children);
    return isCategoricalFeature(node.feature) ? [above, atMost] : [atMost, above];
}

/**
 * Turn the leaf `nodeId` into a split on `feature`, with two new leaves under
 * it: `whenItHolds` for the cases where the condition on screen holds (the
 * feature is at most the threshold, or the condition is true), `otherwise`
 * for the rest.
 */
export function addSplit(tree, nodeId, feature, threshold, whenItHolds, otherwise) {
    const maxId = Math.max(...Object.keys(tree).map(key => parseInt(key) || 0));
    const atMostId = maxId + 1;
    const aboveId = maxId + 2;
    const categorical = isCategoricalFeature(feature);
    tree[nodeId] = { feature, threshold, children: { true: atMostId, false: aboveId } };
    tree[atMostId] = categorical ? otherwise : whenItHolds;
    tree[aboveId] = categorical ? whenItHolds : otherwise;
}

/** Turn the split `nodeId` back into `leaf`, dropping everything below it. */
export function removeSplit(tree, nodeId, leaf) {
    const drop = (id) => {
        dropChildren(tree[id]);
        delete tree[id];
    };
    const dropChildren = (node) => {
        if (!node || !node.children) return;
        for (const child of branchIds(node.children)) {
            if (child !== undefined && child !== null) drop(child);
        }
    };
    dropChildren(tree[nodeId]);
    tree[nodeId] = leaf;
}
