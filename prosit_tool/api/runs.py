"""What-if scenario endpoints (a session can have multiple named SimulationRuns).

Each run owns:
- a ProSiT JSON parameter file (snapshot of the parameters when the run was
  created or last edited)
- optionally a simulation log CSV (set after the run is executed)

The "As-Is" baseline run is created automatically by the discovery endpoint
and is read-only.
"""

import os
import logging
import shutil
from datetime import datetime

from flask import Blueprint, current_app, request, jsonify

from ..extensions import db
from ..models import SimulationRun, SimulationSession, BASELINE_RUN_NAME, utcnow
from ..validators import validate_run_id

from ._decorators import handle_api_errors
from ._shared import remove_file
from .parameters import ParameterError, apply_ui_parameters_to_file, load_parameters_for_ui

logger = logging.getLogger(__name__)
bp = Blueprint('runs', __name__)


def _params_path(filename):
    return os.path.join(current_app.config['UPLOAD_FOLDER'], filename)


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


def _is_baseline_name(name):
    return name.strip().lower() == BASELINE_RUN_NAME.lower()


@bp.route('/api/sessions/<int:session_id>/runs', methods=['GET'])
@handle_api_errors('Failed to list runs')
def list_runs(session_id):
    session = db.get_or_404(SimulationSession, session_id)
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
    session = db.get_or_404(SimulationSession, session_id)

    body = request.get_json(silent=True) or {}
    name = body.get('name')
    name = name.strip() if isinstance(name, str) else ''
    if not name:
        return jsonify({'error': 'Run name is required'}), 400
    if _is_baseline_name(name):
        return jsonify({'error': f'"{BASELINE_RUN_NAME}" is reserved for the baseline run'}), 400

    existing = next((r for r in session.runs if r.name.lower() == name.lower()), None)
    if existing:
        return jsonify({'error': f'A run named "{existing.name}" already exists in this session'}), 409

    from_run_id, err = validate_run_id(body.get('from_run_id'))
    if err:
        return jsonify({'error': err.replace('run_id', 'from_run_id')}), 400
    if from_run_id is not None:
        source_run = SimulationRun.query.filter_by(id=from_run_id, session_id=session_id).first()
        if not source_run:
            return jsonify({'error': 'Source run not found'}), 404
    else:
        source_run = session.get_baseline_run()
    if source_run is None or not source_run.parameters_filename:
        return jsonify({'error': 'Session has no baseline parameters yet'}), 400
    if not os.path.exists(_params_path(source_run.parameters_filename)):
        return jsonify({'error': 'Parameter file of the source scenario is missing on disk'}), 404

    new_run = SimulationRun(
        session_id=session_id,
        name=name,
        is_baseline=False,
        created_at=utcnow(),
    )
    db.session.add(new_run)
    db.session.flush()  # populate new_run.id for the snapshot filename

    snapshot_name = _snapshot_filename(new_run.id, source_run.parameters_filename)
    try:
        _copy_parameters(source_run.parameters_filename, snapshot_name)
        new_run.parameters_filename = snapshot_name

        # Optional inline edit: persist UI-format edits into the new snapshot.
        parameters = body.get('parameters')
        if parameters:
            apply_ui_parameters_to_file(_params_path(snapshot_name), parameters)
    except ParameterError as exc:
        db.session.rollback()
        remove_file(current_app.config['UPLOAD_FOLDER'], snapshot_name)
        return jsonify({'error': str(exc)}), 400
    except Exception:
        db.session.rollback()
        remove_file(current_app.config['UPLOAD_FOLDER'], snapshot_name)
        raise

    session.touch()
    db.session.commit()
    return jsonify({'success': True, 'run': _serialize_run(new_run)})


@bp.route('/api/runs/<int:run_id>', methods=['GET'])
@handle_api_errors('Failed to load run')
def get_run(run_id):
    run = db.get_or_404(SimulationRun, run_id)
    if not run.parameters_filename:
        return jsonify({'error': 'Run has no parameters yet'}), 404

    json_filepath = _params_path(run.parameters_filename)
    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Run parameter file missing on disk'}), 404

    parameters = load_parameters_for_ui(run.session, json_filepath)

    return jsonify({
        'success': True,
        'run': _serialize_run(run),
        'parameters': parameters,
    })


@bp.route('/api/runs/<int:run_id>', methods=['PUT'])
@handle_api_errors('Failed to update run')
def update_run(run_id):
    run = db.get_or_404(SimulationRun, run_id)
    if run.is_baseline:
        return jsonify({'error': 'The baseline (As-Is) run is read-only'}), 400

    body = request.get_json(silent=True) or {}
    parameters = body.get('parameters')
    if not parameters:
        return jsonify({'error': 'No parameters provided'}), 400
    if not run.parameters_filename or not os.path.exists(_params_path(run.parameters_filename)):
        return jsonify({'error': 'Run parameter file missing on disk'}), 404

    try:
        apply_ui_parameters_to_file(_params_path(run.parameters_filename), parameters)
    except ParameterError as exc:
        return jsonify({'error': str(exc)}), 400
    run.session.touch()
    db.session.commit()
    return jsonify({'success': True, 'run': _serialize_run(run)})


@bp.route('/api/runs/<int:run_id>', methods=['PATCH'])
@handle_api_errors('Failed to rename run')
def rename_run(run_id):
    run = db.get_or_404(SimulationRun, run_id)
    if run.is_baseline:
        return jsonify({'error': 'The baseline (As-Is) run cannot be renamed'}), 400

    body = request.get_json(silent=True) or {}
    new_name = body.get('name')
    new_name = new_name.strip() if isinstance(new_name, str) else ''
    if not new_name:
        return jsonify({'error': 'Name is required'}), 400
    if _is_baseline_name(new_name):
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
    run = db.get_or_404(SimulationRun, run_id)
    if run.is_baseline:
        return jsonify({'error': 'The baseline (As-Is) run cannot be deleted'}), 400

    parameters_filename = run.parameters_filename
    simulation_filename = run.simulation_df_filename

    session = run.session
    db.session.delete(run)
    session.touch()
    db.session.commit()

    # Files go only once the row is gone for good: a failed delete must not
    # leave a scenario that points at nothing.
    remove_file(current_app.config['UPLOAD_FOLDER'], parameters_filename)
    remove_file(current_app.config['SIMULATION_FOLDER'], simulation_filename)
    return jsonify({'success': True})


# How many sessions the "Recent Sessions" list shows.
RECENT_SESSIONS = 15


def _session_summary(session):
    used = session.last_used_at or session.created_at
    return {
        'id': session.id,
        'label': session.display_label(),
        'status': session.status,
        # Stored as UTC without a zone: say so, for the browser to show local time.
        'last_used_at': used.isoformat() + 'Z' if used else None,
        'run_count': len(session.runs) if session.runs else 0,
    }


@bp.route('/api/sessions', methods=['GET'])
@handle_api_errors('Failed to list sessions')
def list_sessions():
    """The sessions used most recently, newest first."""
    sessions = (
        SimulationSession.query
        .order_by(
            SimulationSession.last_used_at.desc().nullslast(),
            SimulationSession.created_at.desc(),
        )
        .limit(RECENT_SESSIONS)
        .all()
    )
    return jsonify({'success': True, 'sessions': [_session_summary(session) for session in sessions]})


@bp.route('/api/sessions/<int:session_id>', methods=['DELETE'])
@handle_api_errors('Failed to delete session')
def delete_session(session_id):
    """Remove a session, all its runs, and any files they reference."""
    session = db.get_or_404(SimulationSession, session_id)

    metadata = session.get_parameters() or {}
    upload_files = [metadata.get('pnml_filename'), metadata.get('json_filename'), session.filename]
    simulation_files = []
    for run in session.runs:
        upload_files.append(run.parameters_filename)
        simulation_files.append(run.simulation_df_filename)

    db.session.delete(session)
    db.session.commit()

    for filename in upload_files:
        remove_file(current_app.config['UPLOAD_FOLDER'], filename)
    for filename in simulation_files:
        remove_file(current_app.config['SIMULATION_FOLDER'], filename)
    return jsonify({'success': True})


@bp.route('/api/sessions/<int:session_id>', methods=['PATCH'])
@handle_api_errors('Failed to update session')
def rename_session(session_id):
    """Rename a session. Pass ``display_name: null`` (or empty string) to
    clear the override and revert to the auto-derived label."""
    session = db.get_or_404(SimulationSession, session_id)
    body = request.get_json(silent=True) or {}
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
