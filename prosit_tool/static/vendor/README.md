# Third-party libraries

The page loads these files from here instead of a CDN, so that the tool works
on a machine with no network. They are the files published by their authors,
unmodified: `tests/test_frontend.py` checks each one against its SHA-384.

| File | Package | Licence | Source |
|---|---|---|---|
| `bootstrap/bootstrap.min.css` | bootstrap 5.3.0 | MIT | `https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css` |
| `bootstrap/bootstrap.bundle.min.js` | bootstrap 5.3.0 (includes Popper 2, MIT) | MIT | `https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js` |
| `chart.js/chart.umd.js` | chart.js 4.4.7 | MIT | `https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js` |
| `chartjs-chart-matrix/chartjs-chart-matrix.min.js` | chartjs-chart-matrix 2.0.1 | MIT | `https://cdn.jsdelivr.net/npm/chartjs-chart-matrix@2.0.1/dist/chartjs-chart-matrix.min.js` |
| `feather-icons/feather.min.js` | feather-icons 4.29.2 | MIT | `https://unpkg.com/feather-icons@4.29.2/dist/feather.min.js` |
| `viz-js/viz.js` | @viz-js/viz 3.31.0 | MIT | `https://cdn.jsdelivr.net/npm/@viz-js/viz@3.31.0/dist/viz.js` |

`viz-js/viz.js` contains, compiled to WebAssembly, Graphviz 16.1.0 (Eclipse
Public License 1.0, https://www.graphviz.org) and Expat (MIT,
https://libexpat.github.io).

To update a library, replace its file with the one of the new version and
update the version and the hash in `tests/test_frontend.py` and in this table.
