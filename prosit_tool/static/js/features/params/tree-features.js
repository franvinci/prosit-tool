/**
 * What a split of a decision tree can test: the features available for each
 * kind of tree, and an explanation of each in plain words.
 *
 * A feature is a string. "attribute = value" and "resource = name" are
 * conditions that hold or not; any other feature is a number compared with a
 * threshold (an hour, a count of how often an activity occurred...).
 */

import { state } from '../../core/state.js';

/** True for a feature that is a condition, not a number compared with a threshold. */
export function isCategoricalFeature(feature) {
    return String(feature).includes(' = ');
}

/** Explain a feature to the person reading or building a tree. */
export function getFeatureTooltip(featureValue, parameters = state.parameters) {
    if (featureValue == null || featureValue === '') return '';
    const v = String(featureValue);

    if (v === 'hour') return 'Hour of the day (0-23) when the event occurs.';
    if (v === 'weekday') return 'Day of the week (0=Monday, …, 6=Sunday) when the event occurs.';
    if (v === 'workload') return 'Number of cases active in the system at that moment.';

    if (v.startsWith('resource = ')) {
        const r = v.slice('resource = '.length);
        return `True when the executing resource is «${r}».`;
    }

    if (isCategoricalFeature(v)) {
        const idx = v.indexOf(' = ');
        const attr = v.slice(0, idx);
        const val = v.slice(idx + 3);
        return `True when the case attribute «${attr}» equals «${val}».`;
    }

    const activities = parameters?.process_model?.activities || [];
    const resources = parameters?.resource_params?.resources || [];
    const attrs = parameters?.data_attribute_params?.distribution_data_attributes || {};

    if (activities.includes(v)) {
        return `Counts how many times the case has gone through activity «${v}». The false branch covers cases that have done so at least (threshold + 1) times.`;
    }
    if (resources.includes(v)) {
        return `Counts how many times resource «${v}» has served the case. The false branch covers cases where this happened at least (threshold + 1) times.`;
    }
    if (Object.prototype.hasOwnProperty.call(attrs, v)) {
        return `Numeric threshold on the case attribute «${v}».`;
    }

    return `Feature «${v}».`;
}

const feature = (value, group) => ({ value, label: value, group });

// One condition per value of a categorical attribute, the attribute itself
// (a number) otherwise.
function attributeFeatures(parameters) {
    const attributes = parameters?.data_attribute_params?.distribution_data_attributes || {};
    const categorical = parameters?.data_attribute_params?.label_data_attributes_categorical || [];
    const knownValues = parameters?.data_attribute_params?.attribute_values_label_categorical || {};

    const features = [];
    for (const [attribute, entry] of Object.entries(attributes)) {
        if (!categorical.includes(attribute)) {
            features.push(feature(attribute, 'Trace attributes'));
            continue;
        }
        const values = knownValues[attribute] || Object.keys((entry && entry.values) || entry || {});
        values.forEach(value => features.push(feature(`${attribute} = ${value}`, 'Trace attributes')));
    }
    return features;
}

/**
 * The features a split of a tree of kind `treeType` can use, as
 * `{value, label, group}`; the groups are the headings of the list.
 */
export function generateFeaturesForTreeType(treeType, parameters = state.parameters) {
    const activities = (parameters?.process_model?.activities || []).map(activity => feature(activity, 'Activities'));
    const resources = parameters?.resource_params?.resources || [];
    const attributes = attributeFeatures(parameters);
    const time = [feature('hour', 'Time'), feature('weekday', 'Time')];

    switch (treeType) {
        case 'transition':
            return [...attributes, ...activities];
        case 'resource':
            return [...resources.map(resource => feature(resource, 'Resources')), ...attributes, ...activities];
        case 'arrival':
            return time;
        case 'waiting':
            return [feature('workload', 'Workload'), ...activities, ...attributes];
        case 'execution':
        case 'distribution':
            return [...resources.map(resource => feature(`resource = ${resource}`, 'Resources')), ...activities, ...attributes];
        default:
            return [...time, ...attributes];
    }
}
