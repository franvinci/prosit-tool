/**
 * Reading the column names of an event log before it is uploaded, and
 * guessing which column is the case, the activity, the timestamps and the
 * resource. No page involved: plain text in, names out.
 */

/** Column names of a CSV header line; double-quoted fields may contain commas. */
export function parseCsvHeaderLine(line) {
    const out = [];
    let cur = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (inQuotes) {
            if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
            else if (ch === '"') { inQuotes = false; }
            else { cur += ch; }
        } else {
            if (ch === ',') { out.push(cur.trim()); cur = ''; }
            else if (ch === '"' && cur === '') { inQuotes = true; }
            else { cur += ch; }
        }
    }
    out.push(cur.trim());
    return out.filter(h => h.length > 0);
}

/**
 * Attribute keys found at the start of an XES file. Keys of the trace become
 * `case:<key>`, as in the table pm4py builds from the log; keys of the events
 * are kept as they are.
 */
export function extractXesColumns(text) {
    const out = new Set();
    const keyRe = /<(?:string|date|int|float|boolean|id)\b[^>]*\bkey="([^"]+)"/g;

    // The first <trace>, up to its first <event>.
    const traceMatch = text.match(/<trace[^>]*>([\s\S]*?)(?:<event\b|<\/trace>)/);
    if (traceMatch) {
        let m;
        while ((m = keyRe.exec(traceMatch[1])) !== null) {
            out.add('case:' + m[1]);
        }
    }
    keyRe.lastIndex = 0;

    // The first <event>.
    const eventMatch = text.match(/<event\b[^>]*>([\s\S]*?)<\/event>/);
    if (eventMatch) {
        let m;
        while ((m = keyRe.exec(eventMatch[1])) !== null) {
            out.add(m[1]);
        }
    }
    return Array.from(out);
}

// Exact names first, so that "concept:name" is the activity even when
// "case:concept:name" is among the columns too.
const COLUMN_PATTERNS = {
    case_id: [/^case:concept:name$/, /^case[_ ]?id$/, /^case$/, /^trace[_ ]?id$/, /caseid/],
    activity: [/^concept:name$/, /^activity$/, /^task$/, /^event$/, /activityname/],
    end_ts: [/^time:timestamp$/, /^end[_ ]?(time|ts|timestamp)$/, /complete[_ ]?time/, /^timestamp$/],
    start_ts: [/^start:timestamp$/, /^start[_ ]?(time|ts|timestamp)$/],
    resource: [/^org:resource$/, /^resource$/, /^user$/, /^worker$/],
};

/** For each role, the column that looks like it ('' when none does). */
export function guessColumnMapping(headers) {
    const lower = headers.map(h => h.toLowerCase());
    const guesses = {};
    for (const [role, patterns] of Object.entries(COLUMN_PATTERNS)) {
        guesses[role] = '';
        for (const pattern of patterns) {
            const index = lower.findIndex(h => pattern.test(h));
            if (index >= 0) { guesses[role] = headers[index]; break; }
        }
    }
    return guesses;
}
