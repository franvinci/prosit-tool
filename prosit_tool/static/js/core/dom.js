/**
 * Building blocks for the pages: escaping, delegated events, icons, tooltips.
 */

/**
 * Make a value safe to put in HTML, both as text and inside a quoted
 * attribute. Every name that comes from an event log (activities, resources,
 * attributes) goes through here before it reaches innerHTML.
 */
export function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * CSS selector for the elements whose `attribute` is exactly `value`, whatever
 * characters the value contains (a name from an event log can hold quotes).
 */
export function attrSelector(attribute, value) {
    return `[${attribute}="${CSS.escape(String(value))}"]`;
}

/**
 * A small "i" that explains something when the pointer is on it. The container
 * it ends up in needs initTooltipsIn() once it is in the page.
 */
export function infoIcon(text) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-info ms-1"'
        + ` data-bs-toggle="tooltip" data-bs-placement="top" title="${escapeHtml(text)}"`
        + ' style="cursor: help; width: 14px; height: 14px; color: var(--light-green);">'
        + '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
}

const registry = new Map();   // event type -> Map(action name -> handler)

function dispatch(handlers, event) {
    const origin = event.target instanceof Element ? event.target : event.target && event.target.parentElement;
    const element = origin && origin.closest('[data-action]');
    if (!element) return;
    const handler = handlers.get(element.dataset.action);
    if (handler) handler(element, event);
}

/**
 * Handle `eventType` on every element marked data-action="<name>", including
 * the ones rendered later: one listener on the document per event type.
 *
 *     on('click', { 'delete-session': (element, event) => ... });
 *
 * The handler gets the marked element (its data-* attributes carry the
 * arguments) and the event. The innermost marked element wins, so a button
 * inside a clickable row does not also trigger the row.
 */
export function on(eventType, actions) {
    let handlers = registry.get(eventType);
    if (!handlers) {
        handlers = new Map();
        registry.set(eventType, handlers);
        document.addEventListener(eventType, (event) => dispatch(handlers, event));
    }
    for (const [name, handler] of Object.entries(actions)) {
        if (handlers.has(name)) throw new Error(`Action "${name}" is already handled for ${eventType}`);
        handlers.set(name, handler);
    }
}

/**
 * Wrap feather.replace so that one bad icon (or a node detached while it
 * runs) does not break the page: fall back to replacing icon by icon.
 */
export function patchFeatherReplace() {
    if (!window.feather || window.feather._safeWrapped) return;
    const orig = window.feather.replace.bind(window.feather);
    window.feather._safeWrapped = true;
    window.feather.replace = function (attributes) {
        try {
            return orig(attributes);
        } catch (e) {
            console.warn('feather.replace bulk failed, falling back per-icon:', e);
            const els = Array.from(document.querySelectorAll('[data-feather]'));
            els.forEach((el) => {
                try {
                    const name = el.getAttribute('data-feather');
                    const icon = window.feather.icons[name];
                    if (!icon || !el.parentNode) return;
                    const className = el.getAttribute('class') || '';
                    const attrs = Object.assign({}, attributes || {}, { class: className });
                    const svgString = icon.toSvg(attrs);
                    const tmp = document.createElement('div');
                    tmp.innerHTML = svgString;
                    const newEl = tmp.firstElementChild;
                    if (!newEl) return;
                    Array.from(el.attributes).forEach((a) => {
                        if (a.name === 'class' || a.name === 'data-feather') return;
                        newEl.setAttribute(a.name, a.value);
                    });
                    el.parentNode.replaceChild(newEl, el);
                } catch (err) {
                    console.warn('feather.replace per-icon failed:', el, err);
                }
            });
        }
    };
}

/**
 * Initialize the Bootstrap tooltips inside a container, disposing of existing
 * instances first so that re-renders do not leak duplicates.
 */
export function initTooltipsIn(rootEl) {
    if (!window.bootstrap) return;
    const root = rootEl || document;
    const triggers = root.querySelectorAll('[data-bs-toggle="tooltip"]');
    triggers.forEach(function (el) {
        const existing = bootstrap.Tooltip.getInstance(el);
        if (existing) existing.dispose();
        new bootstrap.Tooltip(el);
    });
}
