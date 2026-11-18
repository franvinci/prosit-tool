/**
 * What a split of a decision tree can test: the features prosit-pm gives to
 * each kind of tree when it simulates, and an explanation of each in plain
 * words.
 *
 * A feature is a string. "attribute = value", "resource = name" and the like
 * are conditions that hold or not; any other feature is a number compared
 * with a threshold (an hour, how often an activity occurred...). A split on a
 * feature the simulator does not provide for that kind of tree makes the
 * simulation fail, so the lists below follow the simulator exactly.
 */

import { state } from '../../core/state.js';
import { isCategoricalFeature } from './trees.js';

/** Explain a feature to the person reading or building a tree. */
export function getFeatureTooltip(featureValue, parameters = state.parameters) {
    if (featureValue == null || featureValue === '') return '';
    const v = String(featureValue);
    const after = (prefix) => v.slice(prefix.length);

    if (v === 'hour') return 'Hour of the day (0-23) when the event occurs.';
    if (v === 'weekday') return 'Day of the week (0=Monday, …, 6=Sunday) when the event occurs.';
    if (v === 'workload') return 'How many events the resource is working on at that moment.';
    if (v === 'queue_length') return 'How many events are already scheduled for the resource after that moment.';

    if (v.startsWith('resource = ')) return `True when the executing resource is «${after('resource = ')}».`;
    if (v.startsWith('waiting_activity = ')) return `True when the activity waiting for the resource is «${after('waiting_activity = ')}».`;
    if (v.startsWith('activity = ')) return `True when the activity to be performed is «${after('activity = ')}».`;

    if (isCategoricalFeature(v)) {
        const idx = v.indexOf(' = ');
        return `True when the case attribute «${v.slice(0, idx)}» equals «${v.slice(idx + 3)}».`;
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
 *
 * What the simulator of prosit-pm 1.0.5 provides:
 *   transition  attributes of the case, how often each activity occurred
 *   resource    how often each resource served the case, the activity to
 *               perform, attributes of the case (+ workload of the resource)
 *   arrival     hour and weekday
 *   execution   the executing resource, hour and weekday, the counts of the
 *               activities, attributes of the case
 *   waiting     hour and weekday, the activity that waits, the counts of the
 *               activities, attributes of the case (+ workload of the resource)
 * The workload features exist only in a model discovered with them.
 */
export function generateFeaturesForTreeType(treeType, parameters = state.parameters) {
    const activities = parameters?.process_model?.activities || [];
    const resources = parameters?.resource_params?.resources || [];
    const attributes = attributeFeatures(parameters);
    const time = [feature('hour', 'Time'), feature('weekday', 'Time')];
    const workload = parameters?.model_options?.use_workload_features
        ? [feature('workload', 'Workload'), feature('queue_length', 'Workload')]
        : [];
    const counts = (names, group) => names.map(name => feature(name, group));
    const conditions = (prefix, names, group) => names.map(name => feature(`${prefix} = ${name}`, group));

    switch (treeType) {
        case 'transition':
            return [...attributes, ...counts(activities, 'Activities')];
        case 'resource':
            return [...counts(resources, 'Resources'), ...conditions('activity', activities, 'Activities'), ...attributes, ...workload];
        case 'arrival':
            return time;
        case 'waiting':
            return [
                ...workload, ...time, ...conditions('waiting_activity', activities, 'Activities'),
                ...counts(activities, 'Activities'), ...attributes,
            ];
        case 'execution':
        case 'distribution':
            return [...conditions('resource', resources, 'Resources'), ...time, ...counts(activities, 'Activities'), ...attributes];
        default:
            return [...time, ...attributes];
    }
}
