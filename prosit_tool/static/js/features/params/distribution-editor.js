/**
 * The editor of one plain distribution: a select for the family and one field
 * per parameter. The execution, waiting, arrival and trace-attribute tabs all
 * use it; each registers what an edit means for its own part of the
 * parameters.
 */

import { escapeHtml, on } from '../../core/dom.js';
import { FAMILIES } from './distributions.js';

const first = (...values) => values.find(value => value !== undefined && value !== null);

// One row of fields per inner list. `value` is what the field shows: the
// parameter as edited, else what the server sent, else a neutral default.
const FIELD_ROWS = {
    fixed: (p) => [[
        { param: 'value', label: 'Fixed Value', min: 1, value: first(p.value, p.mean_value) },
    ]],
    norm: (p) => [
        [
            { param: 'mean', label: 'Mean', min: 1, value: first(p.mean, p.mean_value) },
            { param: 'std', label: 'Std Dev', min: 0, value: p.std },
        ],
        [
            { param: 'min', label: 'Min', min: 0, value: first(p.min, p.min_value) },
            { param: 'max', label: 'Max', min: 1, value: first(p.max, p.max_value) },
        ],
    ],
    expon: (p) => [[
        { param: 'mean', label: 'Mean', min: 1, value: first(p.mean, p.scale, p.mean_value) },
        { param: 'min', label: 'Min', min: 0, value: first(p.min, p.min_value, 0) },
        { param: 'max', label: 'Max', min: 1, value: first(p.max, p.max_value, 100) },
    ]],
    uniform: (p) => [[
        { param: 'min', label: 'Min Value', min: 0, value: first(p.min, p.min_value, 0) },
        { param: 'max', label: 'Max Value', min: 1, value: first(p.max, p.max_value, 100) },
    ]],
    // The server works with scipy's shape and scale; mean and standard
    // deviation say the same and are easier to reason about.
    gamma: (p) => {
        const hasShape = p.shape != null && p.scale != null;
        return [
            [
                {
                    param: 'mean', label: 'Mean', min: 0.0001,
                    title: "Mean of the distribution. Internally maps to scipy gamma's shape/scale.",
                    value: first(p.mean, hasShape ? p.shape * p.scale : null, p.mean_value, 1),
                },
                {
                    param: 'std', label: 'Std Dev', min: 0.0001,
                    title: 'Standard deviation. Smaller = sharper peak around mean.',
                    value: first(p.std, hasShape ? Math.sqrt(p.shape) * p.scale : null, 1),
                },
            ],
            [
                { param: 'min', label: 'Min', value: first(p.min, p.min_value, 0) },
                { param: 'max', label: 'Max', value: first(p.max, p.max_value, 100) },
            ],
        ];
    },
    // scipy's (shape, loc, scale): with no shift the median is the scale, and
    // the shape is the standard deviation on the logarithmic scale.
    lognorm: (p) => [
        [
            {
                param: 'scale', label: 'Median', min: 0,
                title: "Median value of the distribution (scipy 'scale').",
                value: first(p.scale, p.mean_value, 1),
            },
            {
                param: 'shape', label: 'Sigma', min: 0.0001, step: 0.01,
                title: "Spread on the log scale (scipy 'shape' / sigma). Larger = wider distribution.",
                value: first(p.shape, 0.5),
            },
            {
                param: 'loc', label: 'Shift',
                title: "Location offset (scipy 'loc'). Usually 0.",
                value: first(p.loc, 0),
            },
        ],
        [
            { param: 'min', label: 'Min', value: first(p.min, p.min_value, 0) },
            { param: 'max', label: 'Max', value: first(p.max, p.max_value, 100) },
        ],
    ],
};

function targetAttributes(kind, item) {
    return `data-kind="${escapeHtml(kind)}" data-item="${escapeHtml(item)}"`;
}

/** The `<select>` of the family of the distribution of `item`. */
export function renderFamilySelect(kind, item, distribution) {
    const options = FAMILIES
        .map(([value, name]) => `<option value="${value}"${value === distribution ? ' selected' : ''}>${name}</option>`)
        .join('');
    return `<select class="form-select form-select-sm" data-action="set-distribution-family" ${targetAttributes(kind, item)}>${options}</select>`;
}

/** The fields of the parameters of `distribution`, for the entry `item` of the tab `kind`. */
export function renderDistributionParameters(kind, item, distribution, params) {
    const rows = FIELD_ROWS[distribution] ? FIELD_ROWS[distribution](params || {}) : [];
    const target = targetAttributes(kind, item);
    return rows.map((fields, index) => {
        const width = 12 / fields.length;
        const columns = fields.map(field => `
                <div class="col-md-${width}">
                    <label class="form-label small"${field.title ? ` title="${escapeHtml(field.title)}"` : ''}>${field.label}</label>
                    <input type="number" class="form-control form-control-sm"
                           ${field.min !== undefined ? `min="${field.min}" ` : ''}step="${field.step || 0.1}" value="${escapeHtml(field.value)}"
                           data-action="set-distribution-param" data-param="${field.param}" ${target}>
                </div>`).join('');
        return `
            <div class="row${index ? ' mt-2' : ''}">${columns}
            </div>`;
    }).join('');
}

const kinds = new Map();

/**
 * Say what the editor does for the entries of one tab:
 * `update(item, param, value)` stores an edit (`param` is 'distribution' for
 * the family), `refresh(item)` draws the entry again after a change of family.
 */
export function registerDistributionKind(kind, { update, refresh }) {
    kinds.set(kind, { update, refresh });
}

on('change', {
    'set-distribution-param': (element) => {
        const { kind, item, param } = element.dataset;
        kinds.get(kind).update(item, param, parseFloat(element.value));
    },
    'set-distribution-family': (element) => {
        const { kind, item } = element.dataset;
        kinds.get(kind).update(item, 'distribution', element.value);
        kinds.get(kind).refresh(item);
    },
});
