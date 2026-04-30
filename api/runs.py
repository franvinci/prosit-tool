"""What-if scenario endpoints (a session can have multiple named SimulationRuns).

Each run owns:
- a ProSiT JSON parameter file (snapshot of the parameters when the run was
  created or last edited)
- optionally a simulation log CSV (set after the run is executed)

The "As-Is" baseline run is created automatically by the discovery endpoint
and is read-only.
"""

import os
import json
import logging
import shutil
from datetime import datetime

from flask import Blueprint, request, jsonify

from app import app, db
from models import SimulationRun, SimulationSession, BASELINE_RUN_NAME
from format_converters import app_entry_to_prosit, transform_distribution_tree

from ._decorators import handle_api_errors
from ._shared import load_session_prosit
from .parameters import (
    DEFAULT_RESOURCE_WEIGHT,
    DEFAULT_WAITING_DIST,
    _default_calendar,
    convert_app_to_prosit_format,
)

logger = logging.getLogger(__name__)
bp = Blueprint('runs', __name__)


def _params_path(filename):
    return os.path.join(app.config['UPLOAD_FOLDER'], filename)


def _snapshot_filename(run_id, baseline_filename):
    """Filename for a what-if run's JSON snapshot.

    Suffixed with the run id so two scenarios in the same session can't
    collide on disk.
    """
    base = os.path.basename(baseline_filename or 'parameters.json')
    stem, ext = os.path.splitext(base)
    return f"{stem}_run{run_id}{ext or '.json'}"


def _copy_parameters(src_filename, dst_filename):
    src = _params_path(src_filename)
    dst = _params_path(dst_filename)
    shutil.copyfile(src, dst)
    return dst_filename


def _serialize_run(run):
    return run.to_summary()


@bp.route('/api/sessions/<int:session_id>/runs', methods=['GET'])
@handle_api_errors('Failed to list runs')
def list_runs(session_id):
    session = SimulationSession.query.get_or_404(session_id)
    runs = sorted(session.runs, key=lambda r: (not r.is_baseline, r.created_at or datetime.min))
    return jsonify({
        'success': True,
        'runs': [_serialize_run(r) for r in runs],
    })


@bp.route('/api/sessions/<int:session_id>/runs', methods=['POST'])
@handle_api_errors('Failed to create run')
def create_run(session_id):
    """Create a new what-if scenario.

    Body (JSON):
        name (str, required) — must be unique within the session
        parameters (object, optional) — UI-format parameter edits to apply on
            top of the baseline before saving the snapshot
        from_run_id (int, optional) — copy parameters from this run instead of
            the baseline (defaults to baseline)
    """
    session = SimulationSession.query.get_or_404(session_id)

    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Run name is required'}), 400
    if name == BASELINE_RUN_NAME:
        return jsonify({'error': f'"{BASELINE_RUN_NAME}" is reserved for the baseline run'}), 400

    existing = next((r for r in session.runs if r.name.lower() == name.lower()), None)
    if existing:
        return jsonify({'error': f'A run named "{existing.name}" already exists in this session'}), 409

    source_run = None
    if 'from_run_id' in body and body['from_run_id'] is not None:
        source_run = SimulationRun.query.filter_by(
            id=int(body['from_run_id']), session_id=session_id
        ).first()
        if not source_run:
            return jsonify({'error': 'Source run not found'}), 404
    if source_run is None:
        source_run = session.get_baseline_run()
    if source_run is None or not source_run.parameters_filename:
        return jsonify({'error': 'Session has no baseline parameters yet'}), 400

    new_run = SimulationRun(
        session_id=session_id,
        name=name,
        is_baseline=False,
        created_at=datetime.utcnow(),
    )
    db.session.add(new_run)
    db.session.flush()  # populate new_run.id for the snapshot filename

    snapshot_name = _snapshot_filename(new_run.id, source_run.parameters_filename)
    _copy_parameters(source_run.parameters_filename, snapshot_name)
    new_run.parameters_filename = snapshot_name

    # Optional inline edit: persist UI-format edits into the new snapshot.
    parameters = body.get('parameters')
    if parameters:
        _apply_ui_parameters_to_run(new_run, parameters)

    session.touch()
    db.session.commit()
    return jsonify({'success': True, 'run': _serialize_run(new_run)})


@bp.route('/api/runs/<int:run_id>', methods=['GET'])
@handle_api_errors('Failed to load run')
def get_run(run_id):
    run = SimulationRun.query.get_or_404(run_id)
    if not run.parameters_filename:
        return jsonify({'error': 'Run has no parameters yet'}), 404

    json_filepath = _params_path(run.parameters_filename)
    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Run parameter file missing on disk'}), 404

    session = run.session
    session_metadata = session.get_parameters() or {}
    prosit = load_session_prosit(session)
    parameters = prosit.load_parameters_from_json_file(json_filepath)

    if 'process_model' in session_metadata:
        parameters['process_model'].update(session_metadata['process_model'])
    if 'prosit_metrics' in session_metadata:
        merged = parameters.get('prosit_metrics') or {}
        merged.update(session_metadata.get('prosit_metrics') or {})
        parameters['prosit_metrics'] = merged

    return jsonify({
        'success': True,
        'run': _serialize_run(run),
        'parameters': parameters,
    })


@bp.route('/api/runs/<int:run_id>', methods=['PUT'])
@handle_api_errors('Failed to update run')
def update_run(run_id):
    run = SimulationRun.query.get_or_404(run_id)
    if run.is_baseline:
        return jsonify({'error': 'The baseline (As-Is) run is read-only'}), 400

    body = request.get_json() or {}
    parameters = body.get('parameters')
    if not parameters:
        return jsonify({'error': 'No parameters provided'}), 400

    _apply_ui_parameters_to_run(run, parameters)
    run.session.touch()
    db.session.commit()
    return jsonify({'success': True, 'run': _serialize_run(run)})


@bp.route('/api/runs/<int:run_id>', methods=['PATCH'])
@handle_api_errors('Failed to rename run')
def rename_run(run_id):
    run = SimulationRun.query.get_or_404(run_id)
    if run.is_baseline:
        return jsonify({'error': 'The baseline (As-Is) run cannot be renamed'}), 400

    body = request.get_json() or {}
    new_name = (body.get('name') or '').strip()
    if not new_name:
        return jsonify({'error': 'Name is required'}), 400
    if new_name == BASELINE_RUN_NAME:
        return jsonify({'error': f'"{BASELINE_RUN_NAME}" is reserved'}), 400

    clash = next(
        (r for r in run.session.runs
         if r.id != run.id and r.name.lower() == new_name.lower()),
        None,
    )
    if clash:
        return jsonify({'error': f'A run named "{clash.name}" already exists'}), 409

    run.name = new_name
    run.session.touch()
    db.session.commit()
    return jsonify({'success': True, 'run': _serialize_run(run)})


@bp.route('/api/runs/<int:run_id>', methods=['DELETE'])
@handle_api_errors('Failed to delete run')
def delete_run(run_id):
    run = SimulationRun.query.get_or_404(run_id)
    if run.is_baseline:
        return jsonify({'error': 'The baseline (As-Is) run cannot be deleted'}), 400

    if run.parameters_filename:
        try:
            os.unlink(_params_path(run.parameters_filename))
        except OSError:
            pass
    if run.simulation_df_filename:
        sim_path = os.path.join(
            app.config.get('SIMULATION_FOLDER', 'simulations'),
            run.simulation_df_filename,
        )
        try:
            os.unlink(sim_path)
        except OSError:
            pass

    session = run.session
    db.session.delete(run)
    session.touch()
    db.session.commit()
    return jsonify({'success': True})


# --- helpers ---------------------------------------------------------------

def _apply_ui_parameters_to_run(run, ui_params):
    """Convert UI-format parameter edits into ProSiT JSON and overwrite the
    run's snapshot file in place.
    """
    json_filepath = _params_path(run.parameters_filename)
    if not os.path.exists(json_filepath):
        raise FileNotFoundError(f'Snapshot file missing: {run.parameters_filename}')

    with open(json_filepath, 'r') as f:
        prosit_json = json.load(f)
    prosit_json = convert_app_to_prosit_format(ui_params, prosit_json)
    with open(json_filepath, 'w') as f:
        json.dump(prosit_json, f, indent=4)


@bp.route('/api/sessions/<int:session_id>', methods=['DELETE'])
@handle_api_errors('Failed to delete session')
def delete_session(session_id):
    """Remove a session, all its runs, and any files they reference."""
    session = SimulationSession.query.get_or_404(session_id)

    metadata = session.get_parameters() or {}
    upload_files = []
    for key in ('pnml_filename',):
        if metadata.get(key):
            upload_files.append(metadata[key])

    sim_folder = app.config.get('SIMULATION_FOLDER', 'simulations')
    for run in session.runs:
        if run.parameters_filename:
            upload_files.append(run.parameters_filename)
        if run.simulation_df_filename:
            try:
                os.unlink(os.path.join(sim_folder, run.simulation_df_filename))
            except OSError:
                pass

    if session.filename:
        upload_files.append(session.filename)

    for fname in upload_files:
        try:
            os.unlink(_params_path(fname))
        except OSError:
            pass

    db.session.delete(session)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/sessions/<int:session_id>', methods=['PATCH'])
@handle_api_errors('Failed to update session')
def rename_session(session_id):
    """Rename a session. Pass ``display_name: null`` (or empty string) to
    clear the override and revert to the auto-derived label."""
    session = SimulationSession.query.get_or_404(session_id)
    body = request.get_json() or {}
    if 'display_name' not in body:
        return jsonify({'error': 'display_name field is required'}), 400
    raw = body.get('display_name')
    session.display_name = raw.strip() if isinstance(raw, str) and raw.strip() else None
    session.touch()
    db.session.commit()
    return jsonify({
        'success': True,
        'display_name': session.display_name,
        'display_label': session.display_label(),
    })
