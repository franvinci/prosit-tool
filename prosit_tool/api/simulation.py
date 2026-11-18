"""Simulation and download endpoints."""

import io
import os
import logging
import tempfile

import pandas as pd
import pm4py
from flask import Blueprint, current_app, request, jsonify, send_file, send_from_directory

from ..extensions import db
from ..models import SimulationRun, SimulationSession, utcnow
from ..validators import validate_num_instances, validate_run_id, validate_start_timestamp

from ._decorators import handle_api_errors
from ._shared import load_session_prosit, remove_file, unique_timestamp

logger = logging.getLogger(__name__)
bp = Blueprint('simulation', __name__)

# Statuses that only describe work in progress: never the state to go back to.
_TRANSIENT_STATUSES = ('simulating', 'discovering')


def _error(message, status):
    return jsonify({'error': message}), status


def _simulate(session, run, request_data):
    """Validate the request, simulate ``run`` and record the new log.

    A request that cannot be served (bad value, missing file) is answered
    before anything is changed. If the simulation itself fails, the session
    goes back to the status it had: the scenario that failed says nothing about
    the others, which can still be opened and simulated.
    """
    num_instances, err = validate_num_instances(request_data.get('num_instances'))
    if err:
        return _error(err, 400)
    start_timestamp, err = validate_start_timestamp(request_data.get('start_timestamp'))
    if err:
        return _error(err, 400)

    if not run.parameters_filename:
        return _error('This scenario has no parameters yet', 404)
    json_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], run.parameters_filename)
    if not os.path.exists(json_filepath):
        return _error('Stored parameter file not found', 404)

    simulation_folder = current_app.config['SIMULATION_FOLDER']
    previous_status = session.status if session.status not in _TRANSIENT_STATUSES else 'ready'
    session.status = 'simulating'
    session.touch()
    db.session.commit()

    logger.info(
        "Simulating session %s run %s (%s) using %s",
        session.id, run.id, run.name, run.parameters_filename,
    )
    output_filename = f'simulation_{unique_timestamp()}_s{session.id}_r{run.id}.csv'
    try:
        prosit = load_session_prosit(session)
        prosit.load_parameters_from_json_file(json_filepath)
        result_df = prosit.run_simulation(n_traces=num_instances, start_timestamp=start_timestamp)
        result_df.to_csv(os.path.join(simulation_folder, output_filename), index=False)
    except Exception:
        remove_file(simulation_folder, output_filename)
        db.session.rollback()
        session.status = previous_status
        db.session.commit()
        raise  # let @handle_api_errors log it and answer

    replaced = run.simulation_df_filename
    run.simulation_df_filename = output_filename
    run.num_instances = num_instances
    run.last_run_at = utcnow()
    session.status = 'completed'
    session.touch()
    db.session.commit()
    if replaced != output_filename:
        remove_file(simulation_folder, replaced)

    return jsonify({
        'success': True,
        'sim_output_filename': run.simulation_df_filename,
        'num_events': len(result_df),
        'run': run.to_summary(),
        'message': f'Simulation completed with {num_instances} instances, generated {len(result_df)} events',
    })


@bp.route('/api/simulate/<int:session_id>', methods=['POST'])
@handle_api_errors('Simulation failed')
def simulate(session_id):
    """Simulate a session's run.

    Body (JSON):
        num_instances: optional, positive int (default 100)
        start_timestamp: optional ISO-8601 string
        run_id: optional, target a specific what-if scenario; defaults to baseline
    """
    session = db.get_or_404(SimulationSession, session_id)
    request_data = request.get_json(silent=True) or {}

    run_id, err = validate_run_id(request_data.get('run_id'))
    if err:
        return _error(err, 400)
    if run_id is not None:
        run = SimulationRun.query.filter_by(id=run_id, session_id=session.id).first()
        if run is None:
            return _error('Run not found in this session', 404)
    else:
        run = session.get_baseline_run()
        if run is None:
            return _error('Session has no runs yet — discover parameters first', 400)

    return _simulate(session, run, request_data)


@bp.route('/api/runs/<int:run_id>/simulate', methods=['POST'])
@handle_api_errors('Simulation failed')
def simulate_run(run_id):
    """Simulate a specific what-if run. Same semantics as /api/simulate."""
    run = db.get_or_404(SimulationRun, run_id)
    return _simulate(run.session, run, request.get_json(silent=True) or {})


@bp.route('/api/download/<path:filename>')
def download_file(filename):
    """Download a generated simulation file. Path-safe via send_from_directory."""
    folder = current_app.config['SIMULATION_FOLDER']
    try:
        return send_from_directory(folder, filename, as_attachment=True)
    except (FileNotFoundError, NotADirectoryError):
        return jsonify({'error': 'File not found'}), 404


@bp.route('/api/download_xes/<path:filename>')
def download_xes(filename):
    """Convert a simulated CSV to XES on the fly and serve it."""
    folder = os.path.abspath(current_app.config['SIMULATION_FOLDER'])
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
        # Events without a resource (activities nobody performs in the log)
        # must carry no org:resource attribute; converting the DataFrame as-is
        # would write the missing value as a literal "nan" resource.
        event_log = pm4py.convert_to_event_log(df, stream_postprocessing=True)
        pm4py.write_xes(event_log, tmp_path)
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
