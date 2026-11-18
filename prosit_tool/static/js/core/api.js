/**
 * Calls to the server.
 *
 * Every endpoint answers JSON. A failure is `{"error": "..."}` with a 4xx or
 * 5xx status (plus an `error_id` when it was unexpected, to find it in the
 * log). `request` turns that, an unreadable answer and a network failure into
 * an ApiError, so that callers deal with errors in one place.
 */

export class ApiError extends Error {
    constructor(message, { status = 0, body = null } = {}) {
        super(message);
        this.name = 'ApiError';
        /** HTTP status, or 0 when the server could not be reached. */
        this.status = status;
        /** Parsed answer of the server, when there is one. */
        this.body = body;
    }
}

function errorMessage(status, body) {
    if (body && body.error) {
        return body.error_id ? `${body.error} (error id ${body.error_id})` : String(body.error);
    }
    return `The server answered with an error (${status})`;
}

/**
 * Send a request and return the parsed answer.
 *
 * `json` is sent as a JSON body, `form` (a FormData) as it is.
 */
export async function request(url, { method = 'GET', json, form } = {}) {
    const options = { method };
    if (json !== undefined) {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(json);
    } else if (form !== undefined) {
        options.body = form;
    }

    let response;
    try {
        response = await fetch(url, options);
    } catch (error) {
        throw new ApiError('The server cannot be reached. Is ProSiT still running?');
    }

    let body = null;
    try {
        body = await response.json();
    } catch (error) {
        body = null;   // an empty answer, or one that is not JSON
    }

    if (!response.ok || (body && body.success === false)) {
        throw new ApiError(errorMessage(response.status, body), { status: response.status, body });
    }
    if (body === null) {
        throw new ApiError('The server sent an answer that cannot be read', { status: response.status });
    }
    return body;
}

export const getJson = (url) => request(url);
export const postJson = (url, json) => request(url, { method: 'POST', json });
export const putJson = (url, json) => request(url, { method: 'PUT', json });
export const patchJson = (url, json) => request(url, { method: 'PATCH', json });
export const deleteResource = (url) => request(url, { method: 'DELETE' });
