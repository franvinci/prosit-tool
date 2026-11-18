import assert from 'node:assert/strict';
import { test } from 'node:test';

import { generateFeaturesForTreeType, getFeatureTooltip } from '../../prosit_tool/static/js/features/params/tree-features.js';
import {
    addSplit, branchIds, isCategoricalFeature, isTree, removeSplit, shownBranches, singleLeafTimeTree,
} from '../../prosit_tool/static/js/features/params/trees.js';

// ---- shape of a tree --------------------------------------------------------------------

test('a tree is an object with a root named "0"', () => {
    assert.equal(isTree({ '0': { value: 1 } }), true);
    assert.equal(isTree({ distribution: 'norm', parameters: {} }), false);
    assert.equal(isTree(0.5), false);
    assert.equal(isTree(null), false);
});

test('branches are found under either of the names prosit-pm gives them', () => {
    assert.deepEqual(branchIds({ true: 3, false: 4 }), [3, 4]);
    assert.deepEqual(branchIds({ '1': 3, '0': 4 }), [3, 4]);
    assert.deepEqual(branchIds({ True: 3, False: 4 }), [3, 4]);
});

test('a new time tree is one exponential leaf', () => {
    const tree = singleLeafTimeTree();
    assert.deepEqual(Object.keys(tree), ['0']);
    assert.equal(tree['0'].value, 15);
    assert.equal(tree['0'].dist.dist_name, 'expon');
    assert.notEqual(singleLeafTimeTree(), tree);
});

// ---- adding and removing splits ------------------------------------------------------------

// prosit-pm follows the "true" branch when feature <= threshold. A condition is
// a feature worth 1 when it holds, split at 0.5: its "true" branch is the one
// of the cases where it does NOT hold.

test('for a number, the branch shown as true is the one prosit-pm calls true', () => {
    const node = { feature: 'hour', threshold: 17.5, children: { true: 1, false: 2 } };
    assert.deepEqual(shownBranches(node), [1, 2]);
});

test('for a condition, the branch shown as true is the one prosit-pm calls false', () => {
    assert.deepEqual(shownBranches({ feature: 'kind = gold', threshold: 0.5, children: { true: 1, false: 2 } }), [2, 1]);
    assert.deepEqual(shownBranches({ feature: 'resource = Anna', threshold: 0.5, children: { '1': 5, '0': 6 } }), [6, 5]);
});

test('a split on a condition stores the leaf for "it holds" where prosit-pm looks for it', () => {
    const tree = { '0': { value: 0.5 } };
    addSplit(tree, '0', 'kind = gold', 0.5, { value: 0.9 }, { value: 0.1 });
    // kind = gold  ->  the feature is 1  ->  1 <= 0.5 is false  ->  the "false" child
    assert.deepEqual(tree[tree['0'].children.false], { value: 0.9 });
    assert.deepEqual(tree[tree['0'].children.true], { value: 0.1 });
    // and it is shown back the way it was entered
    const [holds, otherwise] = shownBranches(tree['0']);
    assert.deepEqual([tree[holds], tree[otherwise]], [{ value: 0.9 }, { value: 0.1 }]);
});

test('adding a split turns the leaf into a condition with two new leaves', () => {
    const tree = { '0': { feature: 'hour', threshold: 12, children: { true: 1, false: 2 } }, '1': { value: 0.2 }, '2': { value: 0.8 } };
    addSplit(tree, '2', 'weekday', 4.5, { value: 0.1 }, { value: 0.9 });
    assert.deepEqual(tree['2'], { feature: 'weekday', threshold: 4.5, children: { true: 3, false: 4 } });
    assert.deepEqual(tree['3'], { value: 0.1 });
    assert.deepEqual(tree['4'], { value: 0.9 });
    assert.deepEqual(tree['1'], { value: 0.2 });
});

test('the ids of new leaves never collide with the ones in use', () => {
    const tree = { '0': { feature: 'hour', threshold: 1, children: { '1': 7, '0': 3 } }, '7': { value: 1 }, '3': { value: 2 } };
    addSplit(tree, '3', 'hour', 2, { value: 3 }, { value: 4 });
    assert.deepEqual(Object.keys(tree).sort(), ['0', '3', '7', '8', '9']);
});

test('removing a split drops everything below it and nothing else', () => {
    const tree = {
        '0': { feature: 'hour', threshold: 12, children: { true: 1, false: 2 } },
        '1': { feature: 'weekday', threshold: 4.5, children: { '1': 3, '0': 4 } },
        '2': { value: 0.8 },
        '3': { feature: 'hour', threshold: 8, children: { true: 5, false: 6 } },
        '4': { value: 0.4 },
        '5': { value: 0.5 },
        '6': { value: 0.6 },
    };
    removeSplit(tree, '1', { value: 0.3 });
    assert.deepEqual(tree, {
        '0': { feature: 'hour', threshold: 12, children: { true: 1, false: 2 } },
        '1': { value: 0.3 },
        '2': { value: 0.8 },
    });
});

test('removing the root leaves a tree with one leaf', () => {
    const tree = { '0': { feature: 'hour', threshold: 12, children: { true: 1, false: 2 } }, '1': { value: 1 }, '2': { value: 2 } };
    removeSplit(tree, '0', { value: 9 });
    assert.deepEqual(tree, { '0': { value: 9 } });
});

// ---- what a split can test -------------------------------------------------------------------

const parameters = {
    process_model: { activities: ['Check', "O'Neil's review"] },
    resource_params: { resources: ['Anna', 'R&D <team>'] },
    data_attribute_params: {
        distribution_data_attributes: {
            amount: { distribution: 'norm', parameters: { mean: 1, std: 1 } },
            kind: { type: 'categorical', values: { 'a"b': 0.4, '<x>': 0.6 } },
        },
        label_data_attributes_categorical: ['kind'],
    },
};
const values = (treeType) => generateFeaturesForTreeType(treeType, parameters).map(f => f.value);

test('each kind of tree offers the features the simulator gives it', () => {
    const attributes = ['amount', 'kind = a"b', 'kind = <x>'];
    assert.deepEqual(values('arrival'), ['hour', 'weekday']);
    assert.deepEqual(values('transition'), [...attributes, 'Check', "O'Neil's review"]);
    assert.deepEqual(values('resource'), ['Anna', 'R&D <team>', 'activity = Check', "activity = O'Neil's review", ...attributes]);
    assert.deepEqual(values('execution'),
        ['resource = Anna', 'resource = R&D <team>', 'hour', 'weekday', 'Check', "O'Neil's review", ...attributes]);
    assert.deepEqual(values('waiting'),
        ['hour', 'weekday', 'waiting_activity = Check', "waiting_activity = O'Neil's review", 'Check', "O'Neil's review", ...attributes]);
});

test('the workload of a resource can be tested only in a model discovered with it', () => {
    assert.ok(!values('waiting').includes('workload'));
    assert.ok(!values('resource').includes('queue_length'));
    const withWorkload = { ...parameters, model_options: { use_workload_features: true } };
    const of = (treeType) => generateFeaturesForTreeType(treeType, withWorkload).map(f => f.value);
    assert.deepEqual(of('waiting').slice(0, 2), ['workload', 'queue_length']);
    assert.deepEqual(of('resource').slice(-2), ['workload', 'queue_length']);
    for (const treeType of ['transition', 'arrival', 'execution']) assert.ok(!of(treeType).includes('workload'), treeType);
});

test('features are grouped under the headings of the list', () => {
    const groups = new Set(generateFeaturesForTreeType('resource', parameters).map(f => f.group));
    assert.deepEqual([...groups], ['Resources', 'Activities', 'Trace attributes']);
});

test('the values of a categorical attribute listed by the server win over the ones in its distribution', () => {
    const listed = structuredClone(parameters);
    listed.data_attribute_params.attribute_values_label_categorical = { kind: ['only'] };
    assert.deepEqual(generateFeaturesForTreeType('arrival', listed).map(f => f.value), ['hour', 'weekday']);
    assert.ok(generateFeaturesForTreeType('transition', listed).some(f => f.value === 'kind = only'));
});

test('a session without attributes or resources still gets its features', () => {
    assert.deepEqual(generateFeaturesForTreeType('transition', {}), []);
    assert.deepEqual(generateFeaturesForTreeType('waiting', {}).map(f => f.value), ['hour', 'weekday']);
});

test('a condition is told from a number compared with a threshold', () => {
    assert.equal(isCategoricalFeature('kind = a"b'), true);
    assert.equal(isCategoricalFeature('resource = Anna'), true);
    assert.equal(isCategoricalFeature('hour'), false);
});

test('each feature is explained in words', () => {
    assert.match(getFeatureTooltip('hour', parameters), /Hour of the day/);
    assert.match(getFeatureTooltip('resource = Anna', parameters), /executing resource is «Anna»/);
    assert.match(getFeatureTooltip('kind = <x>', parameters), /attribute «kind» equals «<x>»/);
    assert.match(getFeatureTooltip('Check', parameters), /gone through activity «Check»/);
    assert.match(getFeatureTooltip('Anna', parameters), /resource «Anna» has served/);
    assert.match(getFeatureTooltip('amount', parameters), /Numeric threshold/);
    assert.match(getFeatureTooltip('activity = Check', parameters), /activity to be performed is «Check»/);
    assert.match(getFeatureTooltip('waiting_activity = Check', parameters), /waiting for the resource is «Check»/);
    assert.match(getFeatureTooltip('queue_length', parameters), /scheduled for the resource/);
    assert.equal(getFeatureTooltip('', parameters), '');
});
