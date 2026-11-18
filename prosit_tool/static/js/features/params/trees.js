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
 * Ids of the two children of a split: `[taken when the condition holds, taken
 * otherwise]`. prosit-pm names the branches "true"/"false" in memory and
 * "1"/"0" once the tree has been through JSON.
 */
export function branchIds(children) {
    return [
        children.true ?? children['1'] ?? children.True,
        children.false ?? children['0'] ?? children.False,
    ];
}

/** Turn the leaf `nodeId` into a split on `feature`, with two new leaves under it. */
export function addSplit(tree, nodeId, feature, threshold, trueLeaf, falseLeaf) {
    const maxId = Math.max(...Object.keys(tree).map(key => parseInt(key) || 0));
    const trueId = maxId + 1;
    const falseId = maxId + 2;
    tree[nodeId] = { feature, threshold, children: { true: trueId, false: falseId } };
    tree[trueId] = trueLeaf;
    tree[falseId] = falseLeaf;
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
