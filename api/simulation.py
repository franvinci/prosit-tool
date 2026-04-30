"""Simulation and download endpoints."""

import io
import os
import logging
import tempfile
from datetime import datetime

import pandas as pd
import pm4py
from flask import Blueprint, request, jsonify, send_file, send_from_directory

from app import app, db
from models import SimulationRun, SimulationSession
from validators import validate_num_instances

from ._decorators import handle_api_errors
from ._shared import load_session_prosit

logger = logging.getLogger(__name__)
bp = Blueprint('simulation', __name__)


def _resolve_run(session, run_id):
    """Pick the SimulationRun to simulate against.

    Honors an explicit run_id from the request when given (must belong to the
    session); otherwise falls back to the baseline run.
    """
    if run_id is not None:
        run = SimulationRun.query.filter_by(id=int(run_id), session_id=session.id).first()
        if run is None:
            return None, ('Run not found in this session', 404)
        return run, None
    baseline = session.get_baseline_run()
    if baseline is None:
        return None, ('Session has no runs yet — discover parameters first', 400)
    return baseline, None


def _do_simulate(session, run, num_instances, start_timestamp):
    """Run the ProSiT simulator for ``run``, save the CSV, update the row."""
    json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], run.parameters_filename)
    if not os.path.exists(json_filepath):
        return None, ('Stored parameter file not found', 404)

    logger.info(
        "Simulating session %s run %s (%s) using %s",
        session.id, run.id, run.name, run.parameters_filename,
    )
    prosit = load_session_prosit(session)
    prosit.load_parameters_from_json_file(json_filepath)
    result_df = prosit.run_simulation(n_traces=num_instances, start_timestamp=start_timestamp)

    timestamp = int(datetime.now().timestamp())
    output_filename = f'simulation_{timestamp}_s{session.id}_r{run.id}.csv'
    output_path = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), output_filename)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result_df.to_csv(output_path, index=False)

    run.simulation_df_filename = output_filename
    run.num_instances = num_instances
    run.last_run_at = datetime.utcnow()
    return result_df, None


def _parse_start_timestamp(raw):
    if not raw:
        return datetime.now()
    ts = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return ts


def _simulate_session_run(session, request_data, run_id_override=None):
    """Shared simulate logic used by both endpoints.

    Returns a Flask response tuple (json, status_code).
    """
    num_instances, err = validate_num_instances(request_data.get('num_instances'))
    if err:
        return jsonify({'error': err}), 400

    run_id = run_id_override if run_id_override is not None else request_data.get('run_id')
    run, err = _resolve_run(session, run_id)
    if err:
        msg, code = err
        return jsonify({'error': msg}), code

    session.status = 'simulating'
    session.touch()
    db.session.commit()

    start_timestamp = _parse_start_timestamp(request_data.get('start_timestamp'))
    result_df, err = _do_simulate(session, run, num_instances, start_timestamp)
    if err:
        msg, code = err
        session.status = 'ready'
        db.session.commit()
        return jsonify({'error': msg}), code

    session.status = 'completed'
    session.touch()
    db.session.commit()

    return jsonify({
        'success': True,
        'sim_output_filename': run.simulation_df_filename,
        'num_events': len(result_df),
        'run': run.to_summary(),
        'message': f'Simulation completed with {num_instances} instances, generated {len(result_df)} events',
    })


@bp.route('/api/simulate/<int:session_id>', methods=['POST'])
def simulate(session_id):
    """Simulate a session's run.

    Body (JSON):
        num_instances: required, positive int
        start_timestamp: optional ISO-8601 string
        run_id: optional, target a specific what-if scenario; defaults to baseline
    """
    session = None
    try:
        session = SimulationSession.query.get_or_404(session_id)
        return _simulate_session_run(session, request.get_json() or {})
    except Exception:
        logger.exception("Simulation error")
        db.session.rollback()
        try:
            if session is None:
                session = SimulationSession.query.get(session_id)
            if session:
                session.status = 'error'
                db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'error': 'Simulation failed'}), 500


@bp.route('/api/runs/<int:run_id>/simulate', methods=['POST'])
def simulate_run(run_id):
    """Simulate a specific what-if run. Same semantics as /api/simulate."""
    session = None
    try:
        run = SimulationRun.query.get_or_404(run_id)
        session = run.session
        return _simulate_session_run(session, request.get_json() or {}, run_id_override=run.id)
    except Exception:
        logger.exception("Simulation error")
        db.session.rollback()
        if session is not None:
            try:
                session.status = 'error'
                db.session.commit()
            except Exception:
                db.session.rollback()
        return jsonify({'error': 'Simulation failed'}), 500


@bp.route('/api/download/<path:filename>')
def download_file(filename):
    """Download a generated simulation file. Path-safe via send_from_directory."""
    folder = app.config.get('SIMULATION_FOLDER', 'simulations')
    try:
        return send_from_directory(folder, filename, as_attachment=True)
    except (FileNotFoundError, NotADirectoryError):
        return jsonify({'error': 'File not found'}), 404


@bp.route('/api/download_xes/<path:filename>')
def download_xes(filename):
    """Convert a simulated CSV to XES on the fly and serve it."""
    folder = os.path.abspath(app.config.get('SIMULATION_FOLDER', 'simulations'))
    csv_path = os.path.abspath(os.path.join(folder, filename))
    if not csv_path.startswith(folder + os.sep) or not os.path.isfile(csv_path):
        return jsonify({'error': 'File not found'}), 404

    tmp_path = None
    try:
        df = pd.read_csv(csv_path)
        for col in ('time:timestamp', 'start:timestamp', 'enabled:timestamp'):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce', utc=True)

        with tempfile.NamedTemporaryFile(suffix='.xes', delete=False) as tmp:
            tmp_path = tmp.name
        pm4py.write_xes(df, tmp_path)
        with open(tmp_path, 'rb') as f:
            data = f.read()

        xes_name = os.path.splitext(os.path.basename(filename))[0] + '.xes'
        return send_file(
            io.BytesIO(data),
            as_attachment=True,
            download_name=xes_name,
            mimetype='application/xml',
        )
    except Exception:
        logger.exception("XES export failed for %s", filename)
        return jsonify({'error': 'Failed to convert to XES'}), 500
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


