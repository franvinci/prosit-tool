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
 *
 * Most of those numbers are whole: a count, an hour, a day. A tree learnt from
 * a log splits them half way between two values ("≤ 1.5"), which says the
 * same as "≤ 1" and is shown that way.
 */

import { state } from '../../core/state.js';
import { isCategoricalFeature } from './trees.js';

const WHOLE_NUMBERS = ['hour', 'weekday', 'workload', 'queue_length'];
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/**
 * Whether a feature only takes whole numbers: how many times something
 * happened, an hour of the day, a day of the week.
 */
export function isWholeNumberFeature(featureValue, parameters = state.parameters) {
    const v = String(featureValue ?? '');
    if (v === '' || isCategoricalFeature(v)) return false;
    if (WHOLE_NUMBERS.includes(v)) return true;
    const activities = parameters?.process_model?.activities || [];
    const resources = parameters?.resource_params?.resources || [];
    return activities.includes(v) || resources.includes(v);
}

// A threshold as it is written: no more decimals than can mean something.
function tidy(number) {
    return Number.isInteger(number) ? String(number) : String(Math.round(number * 1000) / 1000);
}

/**
 * The largest value of the true branch of a split, for a feature of whole
 * numbers: "≤ 1.5" and "≤ 1" let the same cases through.
 */
function wholeLimit(threshold) {
    const limit = Number(threshold);
    return Number.isFinite(limit) ? Math.floor(limit) : null;
}

/** The condition of a split, as the tree shows it: `amount ≤ 250.5`, `Check ≤ 1`, `kind = gold`. */
export function splitCondition(featureValue, threshold, parameters = state.parameters) {
    const v = String(featureValue ?? '');
    if (isCategoricalFeature(v)) return v;
    const limit = Number(threshold);
    if (threshold == null || threshold === '' || !Number.isFinite(limit)) return `${v} ≤ ${threshold}`;
    return `${v} ≤ ${isWholeNumberFeature(v, parameters) ? Math.floor(limit) : tidy(limit)}`;
}

// The two branches of a split on a count, in words.
function countBranches(limit) {
    if (limit < 0) return 'True branch: no case; false branch: every case.';
    const atMost = limit === 0 ? 'never' : limit === 1 ? 'at most once' : `at most ${limit} times`;
    const more = limit === 0 ? 'at least once' : `${limit + 1} times or more`;
    return `True branch: ${atMost}; false branch: ${more}.`;
}

function hourBranches(limit) {
    if (limit < 0 || limit >= 23) return `True branch: up to hour ${limit}; false branch: later.`;
    const clock = (hour) => String(hour).padStart(2, '0');
    return `True branch: until ${clock(limit)}:59; false branch: from ${clock(limit + 1)}:00.`;
}

function weekdayBranches(limit) {
    if (limit < 0 || limit >= 6) return `True branch: up to day ${limit}; false branch: later.`;
    const upTo = limit === 0 ? 'Monday' : `Monday to ${WEEKDAYS[limit]}`;
    const from = limit === 5 ? 'Sunday' : `${WEEKDAYS[limit + 1]} to Sunday`;
    return `True branch: ${upTo}; false branch: ${from}.`;
}

/**
 * Explain a feature to the person reading or building a tree. With the
 * `threshold` of a split, the explanation says which cases take each branch.
 */
export function getFeatureTooltip(featureValue, parameters = state.parameters, threshold) {
    if (featureValue == null || featureValue === '') return '';
    const v = String(featureValue);
    const after = (prefix) => v.slice(prefix.length);
    const limit = threshold === undefined ? null : wholeLimit(threshold);
    // What to add about the branches when the split is known, else a hint on how to read one.
    const branches = (known, hint) => (limit === null ? hint : known(limit));
    const amounts = (bound) => `True branch: at most ${bound}; false branch: ${bound + 1} or more.`;
    const wholeHint = 'A whole number: "≤ 1" is the branch of the cases where it is 0 or 1.';

    if (v === 'hour') return `Hour of the day (0-23) when the event occurs. ${branches(hourBranches, '')}`.trim();
    if (v === 'weekday') {
        return `Day of the week (0=Monday, …, 6=Sunday) when the event occurs. ${branches(weekdayBranches, '')}`.trim();
    }
    if (v === 'workload') {
        return `How many events the resource is working on at that moment. ${branches(amounts, wholeHint)}`;
    }
    if (v === 'queue_length') {
        return `How many events are already scheduled for the resource after that moment. ${branches(amounts, wholeHint)}`;
    }

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

    const countHint = 'A whole number: "≤ 1" is the branch of the cases where it happened at most once.';
    if (activities.includes(v)) {
        return `How many times the case has gone through activity «${v}» so far. ${branches(countBranches, countHint)}`;
    }
    if (resources.includes(v)) {
        return `How many times resource «${v}» has served the case so far. ${branches(countBranches, countHint)}`;
    }
    if (Object.prototype.hasOwnProperty.call(attrs, v)) {
        const bound = Number(threshold);
        if (threshold === undefined || !Number.isFinite(bound)) return `Numeric threshold on the case attribute «${v}».`;
        return `The case attribute «${v}». True branch: at most ${tidy(bound)}; false branch: more than ${tidy(bound)}.`;
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
