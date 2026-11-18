/**
 * Probability distributions as the editors see them: the families, the
 * parameters each one starts with, their densities for the previews. Plain
 * numbers in and out, no page involved.
 *
 * The parameters are the ones of the API: `mean`/`std`, `min`/`max` and so on,
 * not the positional parameters scipy uses on the server.
 */

/** The families an editor offers, with their names on screen. */
export const FAMILIES = [
    ['fixed', 'Fixed'],
    ['norm', 'Normal'],
    ['expon', 'Exponential'],
    ['uniform', 'Uniform'],
    ['lognorm', 'Log-normal'],
    ['gamma', 'Gamma'],
];

/** Parameters a time distribution (in minutes) starts with when its family is picked. */
export const TIME_FAMILY_DEFAULTS = {
    fixed: { value: 120, min: 120, max: 120 },
    norm: { mean: 120, std: 30 },
    expon: { mean: 120 },
    uniform: { min: 30, max: 240 },
    lognorm: { shape: 0.5, loc: 0, scale: 60, min: 0, max: 600 },
    gamma: { mean: 60, std: 30, min: 0, max: 600 },
};

/**
 * Apply one edit to a time distribution `{distribution, parameters}`:
 * `param` is 'distribution' (a new family, which starts from its defaults) or
 * the name of a parameter.
 */
export function editTimeDistribution(entry, param, value) {
    if (param === 'distribution') {
        entry.distribution = value;
        if (TIME_FAMILY_DEFAULTS[value]) entry.parameters = { ...TIME_FAMILY_DEFAULTS[value] };
        return;
    }
    if (!entry.parameters) entry.parameters = {};
    entry.parameters[param] = value;
    // A fixed value is its own minimum and maximum.
    if (entry.distribution === 'fixed' && param === 'value') {
        entry.parameters.min = value;
        entry.parameters.max = value;
    }
}

/**
 * Parameters of a tree leaf as the editor shows them, from the list prosit-pm
 * keeps (the positional parameters scipy fitted). The exact inverse of
 * distribution_to_prosit() in format_converters.py: opening a leaf and saving
 * it back must not change it.
 *
 * `leaf` is the node the distribution belongs to: its `value` and the bounds
 * of its `dist` stand in for parameters the list does not have.
 */
export function leafParamsFromProsit(family, params, leaf = {}) {
    const editable = {};
    if (!Array.isArray(params)) return editable;
    const dist = leaf.dist || {};
    if (family === 'expon') {
        // scipy expon(loc, scale): shifted by loc, mean = loc + scale.
        const loc = params[0] ?? 0;
        editable.loc = loc;
        editable.mean = params[1] != null ? loc + params[1] : (leaf.value ?? 15);
    } else if (family === 'norm') {
        editable.mean = params[0] ?? leaf.value ?? 15;
        editable.std = params[1] ?? 5;
    } else if (family === 'uniform') {
        // scipy uniform(loc, scale) spans [loc, loc + scale].
        const low = params[0] ?? (dist.min_value ?? 0);
        editable.min = low;
        editable.max = params[1] != null ? low + params[1] : (dist.max_value ?? 100);
    } else if (family === 'fixed') {
        // The simulator samples a fixed leaf from the value of the leaf.
        editable.value = leaf.value ?? params[0] ?? 1;
    } else if (family === 'lognorm') {
        // scipy lognorm(shape, loc, scale).
        editable.shape = params[0] ?? 0.5;
        editable.loc = params[1] ?? 0;
        editable.scale = params[2] ?? leaf.value ?? 1;
    } else if (family === 'gamma') {
        // scipy gamma(a, loc, scale), shown as mean and standard deviation.
        const a = params[0] ?? 2.0;
        const loc = params[1] ?? 0;
        const scale = params[2] ?? 1;
        editable.loc = loc;
        editable.mean = loc + a * scale;
        editable.std = Math.sqrt(a) * scale;
    }
    return editable;
}

// Lanczos approximation of the logarithm of the Gamma function (for the gamma density).
function logGamma(z) {
    if (z < 0.5) {
        return Math.log(Math.PI / Math.sin(Math.PI * z)) - logGamma(1 - z);
    }
    const g = 7;
    const c = [
        0.99999999999980993, 676.5203681218851, -1259.1392167224028,
        771.32342877765313, -176.61502916214059, 12.507343278686905,
        -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
    ];
    z -= 1;
    let x = c[0];
    for (let i = 1; i < g + 2; i++) x += c[i] / (z + i);
    const t = z + g + 0.5;
    return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}

/** Density of `distribution` at `x`, or null for a family that is not known. */
export function distributionPdf(distribution, params, x) {
    switch (distribution) {
        case 'fixed': {
            const v = parseFloat(params.value ?? 0);
            return Math.abs(x - v) < 1e-6 ? 1 : 0;
        }
        case 'norm': {
            const mean = parseFloat(params.mean ?? 0);
            const std = parseFloat(params.std ?? 1);
            if (std <= 0) return 0;
            return Math.exp(-((x - mean) ** 2) / (2 * std * std)) / (std * Math.sqrt(2 * Math.PI));
        }
        case 'expon': {
            // mean = shift + scale; a mean at or below the shift is read as a
            // plain exponential (same rule as the server).
            const mean = parseFloat(params.mean ?? 1);
            let loc = parseFloat(params.loc ?? 0) || 0;
            if (mean <= loc) loc = 0;
            const scale = mean - loc;
            if (x < loc || scale <= 0) return 0;
            return Math.exp(-(x - loc) / scale) / scale;
        }
        case 'uniform': {
            const lo = parseFloat(params.min ?? 0);
            const hi = parseFloat(params.max ?? 1);
            if (hi <= lo) return 0;
            return (x >= lo && x <= hi) ? 1 / (hi - lo) : 0;
        }
        case 'lognorm': {
            // scipy lognorm: shape = sigma of underlying normal, loc = shift, scale = exp(mu)
            const shape = parseFloat(params.shape ?? 0.5);
            const loc = parseFloat(params.loc ?? 0);
            const scale = parseFloat(params.scale ?? 1);
            const t = x - loc;
            if (t <= 0 || shape <= 0 || scale <= 0) return 0;
            const z = (Math.log(t) - Math.log(scale)) / shape;
            return Math.exp(-0.5 * z * z) / (t * shape * Math.sqrt(2 * Math.PI));
        }
        case 'gamma': {
            // UI surfaces mean/std → derive scipy gamma's (shape a, scale).
            const loc = parseFloat(params.loc ?? 0) || 0;
            const mean = parseFloat(params.mean ?? 1) - loc;
            const std = parseFloat(params.std ?? 1);
            const t = x - loc;
            if (mean <= 0 || std <= 0 || t < 0) return 0;
            const a = (mean * mean) / (std * std);
            const scale = (std * std) / mean;
            if (a <= 0 || scale <= 0) return 0;
            const logPdf = (a - 1) * Math.log(Math.max(t, 1e-12)) - t / scale - a * Math.log(scale) - logGamma(a);
            return Math.exp(logPdf);
        }
        default: return null;
    }
}

/** The interval `[from, to]` worth drawing for `distribution`, or null. */
export function distributionRange(distribution, params) {
    switch (distribution) {
        case 'fixed': {
            const v = parseFloat(params.value ?? 0);
            return [v - 1, v + 1];
        }
        case 'norm': {
            const mean = parseFloat(params.mean ?? 0);
            const std = parseFloat(params.std ?? 1);
            return [mean - 4 * std, mean + 4 * std];
        }
        case 'expon': {
            const mean = parseFloat(params.mean ?? 1);
            let loc = parseFloat(params.loc ?? 0) || 0;
            if (mean <= loc) loc = 0;
            return [loc, loc + Math.max(1, 5 * (mean - loc))];
        }
        case 'uniform': {
            const lo = parseFloat(params.min ?? 0);
            const hi = parseFloat(params.max ?? 1);
            const pad = Math.max(1, (hi - lo) * 0.1);
            return [lo - pad, hi + pad];
        }
        case 'lognorm': {
            const shape = parseFloat(params.shape ?? 0.5);
            const loc = parseFloat(params.loc ?? 0);
            const scale = parseFloat(params.scale ?? 1);
            const lo = loc;
            const hi = loc + scale * Math.exp(3 * shape);
            return [lo, hi];
        }
        case 'gamma': {
            // A fitted gamma can start far below its mean (large shape, large
            // negative shift): show the part where the density is.
            const loc = parseFloat(params.loc ?? 0) || 0;
            const mean = parseFloat(params.mean ?? 1);
            const std = parseFloat(params.std ?? 1);
            const lo = Math.max(loc, mean - 4 * std);
            return [lo, Math.max(lo + 1, mean + 4 * std)];
        }
        default: return null;
    }
}

// Parameters a trace attribute starts with when its family is picked.
const ATTRIBUTE_FAMILY_DEFAULTS = {
    fixed:   { value: 1.0, min: 1.0, max: 1.0 },
    norm:    { mean: 15.0, std: 5.0, min: 0.0, max: 60.0 },
    expon:   { mean: 15.0, min: 0.0, max: 60.0 },
    uniform: { min: 0.0, max: 60.0 },
    lognorm: { shape: 0.5, loc: 0.0, scale: 15.0, min: 0.0, max: 60.0 },
    gamma:   { mean: 15.0, std: 8.0, min: 0.0, max: 60.0 },
};

// Different families name the same idea differently: the fixed "value", the
// normal "mean" and the log-normal "scale" are all the typical value.
const PARAM_ALIASES = {
    value: ['mean', 'scale'],
    mean:  ['value', 'scale'],
    scale: ['mean', 'value'],
};

/**
 * Parameters of a trace attribute after a change of family: what the old and
 * the new family have in common is kept, the rest starts from the defaults.
 */
export function mergeDistParams(oldParams, newDist) {
    const defaults = ATTRIBUTE_FAMILY_DEFAULTS[newDist] || {};
    const merged = { ...defaults };
    if (!oldParams || typeof oldParams !== 'object' || Array.isArray(oldParams)) return merged;
    for (const k of Object.keys(defaults)) {
        const direct = parseFloat(oldParams[k]);
        if (Number.isFinite(direct)) {
            merged[k] = direct;
            continue;
        }
        const aliases = PARAM_ALIASES[k] || [];
        for (const a of aliases) {
            const v = parseFloat(oldParams[a]);
            if (Number.isFinite(v)) { merged[k] = v; break; }
        }
    }
    // A fixed value is its own minimum and maximum.
    if (newDist === 'fixed' && merged.value != null) {
        merged.min = merged.value;
        merged.max = merged.value;
    }
    return merged;
}
