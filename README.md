# ProSiT — PROcess SImulation Tool

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)
[![Built on prosit-pm](https://img.shields.io/badge/built%20on-prosit--pm%201.0.3-success.svg)](https://pypi.org/project/prosit-pm/)


ProSiT is a web-based tool for **interactive and transparent business process simulation**. Given an event log (XES or CSV) and an optional Petri net process model, it discovers simulation parameters — arrival rates, execution and waiting times, resource assignments, routing probabilities, and case-level attributes — and lets users edit them through a graphical interface before running discrete-event simulations.

The tool is built on top of the [`prosit-pm`](https://pypi.org/project/prosit-pm/) Python library, which provides the underlying rule-aware simulation engine. ProSiT exposes the engine through a Flask web application that adds end-to-end workflow support: data ingestion, parameter discovery, scenario configuration, accuracy assessment against the original log, and visual analytics on the simulated traces.

Unlike opaque deep-learning simulators, ProSiT keeps every step — the discovered Decision Tree rules, the fitted distributions, the resource calendars — inspectable and editable. The same screen that shows a discovered parameter is the screen where the analyst can override it to design a what-if scenario.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Workflow](#workflow)
- [Input Format](#input-format)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Citation](#citation)
- [License](#license)

---

## Installation

**Requirements:** Python >= 3.10. The Docker option does not require Python on the host.

### Option 1 — Docker (recommended)

Docker bundles the Python environment, system dependencies (Graphviz), and the application server in a single image.

```bash
git clone https://github.com/franvinci/prosit-tool
cd prosit-tool

# SESSION_SECRET is required in production. Generate one once and export it.
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

docker-compose up -d --build
```

The application is then available at `http://localhost:5050`.

Platform-specific helper scripts are provided under `installer/`:

| Platform | Setup | Run | Stop |
|---|---|---|---|
| Windows | `installer\windows\setup-windows.bat` | `installer\windows\run-docker.bat` | `installer\windows\stop-docker.bat` |
| Ubuntu / Linux | `installer/ubuntu/setup-ubuntu.sh` | `installer/ubuntu/run-docker.sh` | `installer/ubuntu/stop-docker.sh` |
| macOS | `installer/macos/setup-macos.sh` | `installer/macos/run-docker.sh` | `installer/macos/stop-docker.sh` |

### Option 2 — Conda (local)

```bash
git clone https://github.com/franvinci/prosit-tool
cd prosit-tool

conda env create -f environment.yml
conda activate prosit-tool

python main.py
```

The application is then available at `http://localhost:5050`.

### Dependencies

| Package | Version | Purpose |
|---|---|---|
| `prosit-pm` | 1.0.3 | Core simulation engine (parameter discovery + discrete-event simulation) |
| `pm4py` | 2.7 | Event log parsing, Petri net discovery and conformance |
| `flask` | 3.1 | Web framework |
| `flask-sqlalchemy` | 3.1 | Session persistence (SQLite by default) |
| `gunicorn` | 23.0 | Production WSGI server |
| `scikit-learn` | 1.6 | Decision tree models (batch discovery) |
| `river` | 0.22 | Hoeffding Adaptive Tree (incremental discovery) |
| `scipy` | 1.14 | Distribution fitting and sampling |
| `pandas` | 2.2 | DataFrame manipulation |
| `numpy` | 1.26 | Numerical operations |
| `matplotlib` | 3.10 | Visualisation rendering |
| `seaborn` | 0.13 | Statistical plots |
| `graphviz` | 0.21 | Process model rendering (also requires the system Graphviz binary) |
| `log-distance-measures` | 2.0 | Accuracy metrics between real and simulated logs |

---

## Quick Start

After starting the application:

1. Open `http://localhost:5050` in a browser.
2. Upload an event log. XES is supported natively; CSV requires a column mapping (case ID, activity, end timestamp, optional start timestamp and resource).
3. Optionally provide your own Petri net in PNML format. Otherwise, the Inductive Miner discovers one from the log.
4. Configure the discovery parameters (noise threshold, decision tree depth, multitasking, attribute mode) and run discovery.
5. Inspect and edit the discovered parameters: control flow weights, resource selection, time distributions, calendars, multitasking capacity, case-attribute distributions.
6. (Optional) Create one or more **what-if runs** as variants of the baseline.
7. Run the simulation, configure number of traces and starting timestamp.
8. Compare the simulated log against the real log via accuracy metrics, and inspect the generated process maps, cycle-time distributions, resource heatmaps, and waiting-time analyses.
9. Export the parameter file or the simulated log.

The example logs under `example_data/` (`purchasing.xes`, `bpi12.xes`, `bpi17_march.xes`, `synloan.xes`, `onboard_client.xes`, `purchasing.csv`) can be used to try the workflow end-to-end without any preparation.

---

## Workflow

ProSiT supports an end-to-end pipeline organised in five phases.

### 1. Data Ingestion

- **Event Log Upload.** Accepts XES or CSV. CSV requires a column mapping; XES is read with `pm4py` directly.
- **Process Model Import.** Optionally provide a Petri net in PNML format. Otherwise, ProSiT applies the Inductive Miner with the chosen noise threshold.
- **Validation.** The uploaded log must contain a case identifier, an activity name, and a completion timestamp. A start timestamp and a resource column are optional but recommended — the tool falls back to defaults (start = end timestamp, resource = `unknown`) when absent.

### 2. Parameter Discovery

ProSiT delegates the actual learning to the `prosit-pm` library. The web interface exposes the most relevant knobs:

| Setting | Default | Effect |
|---|---|---|
| **Noise threshold** | `0.2` | Inductive Miner filtering threshold (range 0–1) |
| **Max decision-tree depth** | `0` | `0` disables rules (pure distributions); higher values produce richer per-leaf models. CV selects the best depth up to the chosen ceiling |
| **Multitasking threshold** | `0.05` | Minimum fraction of concurrent events for a resource to be considered multitasking |
| **Attribute mode** | `distribution` | Independent per-attribute distributions, or `empirical` for joint sampling (preserves correlations) |
| **Incremental discovery** | off | When on, uses Hoeffding Adaptive Trees from `river` (gives more weight to recent traces) |
| **Grace period** | `1000` | (Incremental only) observations before the tree considers splitting a node |
| **Random seed** | `72` | Controls reproducibility |

What ProSiT discovers from the log:

| Parameter | What it models |
|---|---|
| Arrival time | Inter-arrival time between consecutive cases, conditional on hour and weekday |
| Execution time | Working-hours duration of each activity, conditional on resource and case context |
| Waiting time | Queue delay after a resource becomes free, conditional on workload and case context |
| Control flow | Routing probability at each decision point, conditional on case history |
| Resource selection | Per (activity, candidate resource) classifier conditional on resource-usage history and case attributes |
| Calendars | Working hours per resource and for case arrivals |
| Multitasking | Maximum concurrent tasks per resource |
| Data attributes | Joint or per-attribute distribution of case-level data attributes |

### 3. Interactive Scenario Configuration

Every discovered parameter is editable in the UI:

- **Control flow.** Adjust transition weights at each decision point.
- **Resource matrix.** Toggle which resources can perform which activities, edit per-resource weights and capacity.
- **Calendars.** Edit weekday/hour availability per resource and for case arrivals.
- **Time distributions.** Inspect each fitted distribution (or per-leaf distribution when rules are active) and override its parameters.
- **Case attributes.** Inspect and modify the discovered attribute distribution.

Edits can be saved as **what-if runs** alongside the baseline (As-Is) configuration. Each run is an independent simulation scenario and can be compared against the others.

### 4. Accuracy Assessment

The tool evaluates simulation quality by comparing the simulated log against the original event data using:

- **Control-flow similarity.** N-gram distance between case sequences.
- **Temporal accuracy.** Distributional metrics for arrival, execution, and waiting times.
- **Resource behaviour.** Realism of resource handover patterns.
- **Cycle time.** Distance between empirical cycle-time distributions.

Metrics are computed via the [`log-distance-measures`](https://pypi.org/project/log-distance-measures/) library on the baseline run.

### 5. Simulation Execution

- **Configuration.** Number of traces (1–10,000) and starting timestamp.
- **Execution.** Discrete-event simulation runs server-side; progress is streamed to the UI.
- **Visual analytics.** Process maps annotated with frequency or performance, cycle-time histograms, resource utilisation heatmaps, per-activity execution and waiting-time distributions, and side-by-side comparisons between the real and simulated logs.
- **Export.** The simulated log is downloadable as XES or CSV; the parameter file is downloadable as the JSON format consumed by `prosit-pm`.

---

## Input Format

### XES

XES files are read directly with `pm4py`. The default attribute names are expected: `case:concept:name`, `concept:name`, `time:timestamp`, optionally `start:timestamp` and `org:resource`. If your XES uses different attribute names, you can provide a mapping at upload time.

### CSV

CSV uploads always require a mapping form with at least:

- **Case ID column** — unique identifier of each case.
- **Activity column** — name of the activity.
- **End timestamp column** — completion time of the event.

Optional fields:

- **Start timestamp column** — defaults to the end timestamp if not provided.
- **Resource column** — defaults to `unknown` if not provided.

Timestamps must be parseable by `pandas.to_datetime` (ISO 8601 is the safest choice). The CSV is converted to XES on the server before discovery starts.

### PNML

The optional Petri net file is read with `pm4py.read_pnml`. When provided, ProSiT skips the Inductive Miner step and uses the supplied net directly.

---

## Architecture

ProSiT is a Flask application with a thin server-side template layer and a JavaScript frontend that drives all interactive parameter editing. State is persisted per session in SQLite via SQLAlchemy. The simulation engine itself is the `prosit-pm` library, invoked through `prosit_integration.py`.

![System Architecture](doc/diagram.png)

The integration layer (`prosit_integration.py`, `format_converters.py`) is responsible for translating between the JSON shape the UI exchanges with the browser and the typed objects (`SimulatorParameters`) consumed by `prosit-pm`. This split keeps the UI free of any direct dependency on the engine internals.

---

## Project Structure

```
prosit-tool/
├── app.py                  # Flask application factory
├── main.py                 # Entry point (launches gunicorn or the dev server)
├── models.py               # SQLAlchemy models (SimulationSession, Run)
├── config.py               # Centralised configuration constants
├── validators.py           # Request input validators
├── api/                    # Flask blueprints
│   ├── upload.py           # XES/CSV/PNML upload + column mapping
│   ├── discovery.py        # Petri net + parameter discovery
│   ├── parameters.py       # GET/PUT discovered parameters
│   ├── simulation.py       # Simulation execution and metrics
│   ├── runs.py             # What-if scenario management
│   ├── visualization.py    # Chart and process-map renderers
│   ├── errors.py           # JSON error handlers
│   ├── _shared.py          # Cross-blueprint helpers
│   └── _decorators.py      # @handle_api_errors decorator
├── prosit_integration.py   # prosit-pm integration layer
├── format_converters.py    # UI <-> prosit-pm distribution conversions
├── evaluation.py           # Accuracy metrics (real vs simulated)
├── templates/              # Jinja templates
├── static/                 # CSS, JavaScript, static assets
├── installer/              # Platform-specific Docker helper scripts
├── example_data/           # Sample XES/CSV logs
├── tests/                  # Pytest suite
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile              # Production image definition
├── environment.yml         # Conda environment specification
├── LICENSE                 # MIT License
└── README.md               # This documentation
```

---

## API Endpoints

The HTTP API is what the in-browser frontend uses; it is also usable directly for scripted workflows.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Main application interface |
| `POST` | `/api/upload` | Upload XES or CSV log (and optional PNML); creates a session |
| `POST` | `/api/discover/<session_id>` | Run discovery (Petri net + parameters) |
| `GET` | `/api/discover/<session_id>/progress` | Discovery progress stream |
| `GET` | `/api/parameters/<session_id>` | Load discovered parameters for a session |
| `PUT` | `/api/parameters/<session_id>` | Save edited parameters for the baseline run |
| `POST` | `/api/simulate/<session_id>` | Run a simulation for the baseline run |
| `POST` | `/api/metrics/<session_id>` | Compute accuracy metrics (real vs simulated) |
| `GET` | `/api/sessions/<session_id>/runs` | List what-if runs |
| `POST` | `/api/sessions/<session_id>/runs` | Create a new what-if run |
| `GET` | `/api/runs/<run_id>` | Load parameters of a specific run |
| `PUT` | `/api/runs/<run_id>` | Replace parameters of a run |
| `PATCH` | `/api/runs/<run_id>` | Patch run metadata |
| `POST` | `/api/runs/<run_id>/simulate` | Run the simulation for a specific run |
| `DELETE` | `/api/runs/<run_id>` | Delete a run |
| `PATCH` | `/api/sessions/<session_id>` | Update session metadata |
| `DELETE` | `/api/sessions/<session_id>` | Delete a session |
| `GET` | `/api/download/<filename>` | Download a generated CSV |
| `GET` | `/api/download_xes/<filename>` | Download a generated log as XES |
| `GET` | `/api/get_activities_and_resources/<session_id>` | List activities/resources from the simulated log |
| `GET` | `/api/get_visualization/<session_id>/<visualization_type>` | Render a chart from the simulated log |

---

## Configuration

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `FLASK_ENV` | `production` | Flask environment (`development` enables debug) |
| `FLASK_PORT` | `5050` | Port the application binds to |
| `DATABASE_URL` | `sqlite:///prosit.db` | SQLAlchemy connection string |
| `SESSION_SECRET` | (required in production) | Secret key for Flask sessions. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `MAX_CONTENT_LENGTH` | `100 MB` | Maximum upload size |

### Constants

Other defaults (discovery thresholds, simulation bounds, upload folder, simulation folder) are defined in `config.py`. Edit the `Config` class to change them.

### Database

SQLite is used by default; any SQLAlchemy-supported database can be plugged in by changing `DATABASE_URL`. A connection pool with a 300-second recycle is configured, suitable for hosted PostgreSQL or MySQL.

---

## Troubleshooting

### Docker

- **Docker not starting.** Ensure Docker Desktop is running. On Windows/Linux, verify that virtualisation is enabled in BIOS. On macOS, wait for the whale icon to settle in the menu bar.
- **Port 5050 already in use.** Edit the `ports` mapping in `docker-compose.yml`. macOS uses port 5000 for AirPlay, so 5050 was chosen as a less conflict-prone default — change it again if needed.
- **Build errors on Apple Silicon.** Update Docker Desktop. The Dockerfile detects the host architecture automatically.

### Application

- **Memory issues during simulation.** Increase Docker memory allocation, or reduce the number of cases / decision tree depth.
- **File upload errors.** Check that the file is under 100 MB and that the format is XES or CSV. For CSV, ensure the column mapping is provided.
- **CSV `time` parsing errors.** Timestamps must be parseable by `pandas.to_datetime`. Prefer ISO 8601.

### Logs

- View application logs: `docker-compose logs -f`
- Check container status: `docker-compose ps`
- Restart application: `docker-compose restart`

---

## Development

```bash
# Set up the environment
conda env create -f environment.yml
conda activate prosit-tool

# Run the test suite
pytest

# Run in development mode (debug + auto-reload)
FLASK_ENV=development python main.py
```

Tests live under `tests/` and cover smoke, security, and unit-level behaviour. The pytest configuration is in `pytest.ini`.

---

## Citation

Version [v0.1.0](https://github.com/franvinci/prosit-tool/releases/tag/v0.1.0) of ProSiT corresponds to the implementation presented in the following paper. Please cite it if you use the tool in academic work:

> Vinci, F., Park, G., van der Aalst, W. M. P., de Leoni, M. (2026). ProSiT: A Tool for Interactive and Transparent Process Simulations. In: *Proceedings of the International Conference on Service Oriented Computing (ICSOC): Demonstrations and Resources*. Lecture Notes in Computer Science, Springer.

BibTeX:

```bibtex
@inproceedings{VinciProSiT2026,
  author    = {Francesco Vinci and Gyunam Park and Wil M. P. van der Aalst and Massimiliano de Leoni},
  title     = {{ProSiT}: A Tool for Interactive and Transparent Process Simulations},
  booktitle = {Proceedings of the International Conference on Service Oriented Computing (ICSOC): Demonstrations and Resources},
  year      = {2026},
  publisher = {Springer},
  series    = {Lecture Notes in Computer Science}
}
```

The underlying simulation engine is described in:

> Vinci, F., Park, G., van der Aalst, W. M. P., de Leoni, M. (2026). Reliable and Configurable Process Simulations via Probabilistic White-Box Models. In: *Service-Oriented Computing — ICSOC 2025*. Lecture Notes in Computer Science, vol 16321. Springer, Singapore. https://doi.org/10.1007/978-981-95-5015-9_24

---

## License

MIT License — see [LICENSE](LICENSE) for details.
