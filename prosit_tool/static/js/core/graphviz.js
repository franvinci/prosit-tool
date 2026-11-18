/**
 * Graphviz in the browser: turning the description of a graph (DOT) into a
 * drawing (SVG).
 *
 * The server only describes what to draw; the layout is computed here, by
 * Graphviz compiled to WebAssembly (viz-js). The library is over a megabyte,
 * so it is loaded the first time something has to be drawn.
 */

let loading = null;

function graphviz() {
    if (!loading) {
        loading = import('../../vendor/viz-js/viz.js').then(({ instance }) => instance());
        // A failed load must not be remembered: the next drawing tries again.
        loading.catch(() => { loading = null; });
    }
    return loading;
}

/** Draw `dot` and return the `<svg>` element, not yet in the page. */
export async function renderDot(dot) {
    const viz = await graphviz();
    return viz.renderSVGElement(dot);
}
