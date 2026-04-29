"""Simulation, download, and parameter-export endpoints."""

import os
import json
import logging
import tempfile
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file, send_from_directory

from app import app, db
from models import SimulationSession
from validators import validate_num_instances

from ._shared import load_session_prosit

logger = logging.getLogger(__name__)
bp = Blueprint('simulation', __name__)


@bp.route('/api/simulate/<int:session_id>', methods=['POST'])
def simulate(session_id):
    """Generate a simulated event log for a session."""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        parameters = session.get_parameters()
        if not parameters:
            return jsonify({'error': 'No parameters found'}), 404

        request_data = request.get_json() or {}
        num_instances, err = validate_num_instances(request_data.get('num_instances'))
        if err:
            return jsonify({'error': err}), 400

        session.status = 'simulating'
        db.session.commit()

        start_timestamp_str = request_data.get('start_timestamp')
        if start_timestamp_str:
            start_timestamp = datetime.fromisoformat(start_timestamp_str.replace('Z', '+00:00'))
        else:
            start_timestamp = datetime.fromisoformat(str(datetime.now()).replace('Z', '+00:00'))

        logger.info(f"Starting simulation for session {session_id} with {num_instances} instances")

        session_metadata = session.get_parameters()
        json_filename = session_metadata.get('json_filename')
        if not json_filename:
            return jsonify({'error': 'No stored parameters found for this session'}), 400

        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        if not os.path.exists(json_filepath):
            return jsonify({'error': 'Stored parameter file not found'}), 404

        logger.info(f"Using stored modified parameters from {json_filename}")
        prosit = load_session_prosit(session)
        prosit.load_parameters_from_json_file(json_filepath)
        result_df = prosit.run_simulation(n_traces=num_instances, start_timestamp=start_timestamp)

        timestamp = int(datetime.now().timestamp())
        output_filename = f'simulation_{timestamp}_{session_id}.csv'
        output_path = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result_df.to_csv(output_path, index=False)

        session.status = 'completed'
        session.simulation_df_filename = output_filename
        db.session.commit()

        return jsonify({
            'success': True,
            'sim_output_filename': output_filename,
            'num_events': len(result_df),
            'message': f'Simulation completed with {num_instances} instances, generated {len(result_df)} events',
        })

    except Exception as e:
        logger.error(f"Simulation error: {e}")
        session = SimulationSession.query.get(session_id)
        if session:
            session.status = 'error'
            db.session.commit()
        return jsonify({'error': f'Simulation failed: {e}'}), 500


@bp.route('/api/download/<path:filename>')
def download_file(filename):
    """Download a generated simulation file. Path-safe via send_from_directory."""
    folder = app.config.get('SIMULATION_FOLDER', 'simulations')
    try:
        return send_from_directory(folder, filename, as_attachment=True)
    except (FileNotFoundError, NotADirectoryError):
        return jsonify({'error': 'File not found'}), 404


@bp.route('/api/export_parameters/<int:session_id>')
def export_parameters(session_id):
    """Export the current ProSiT JSON parameter file for a session."""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        session_metadata = session.get_parameters()
        if not session_metadata:
            return jsonify({'error': 'No parameters found'}), 404

        json_filename = session_metadata.get('json_filename')
        if not json_filename:
            return jsonify({'error': 'No ProSiT JSON file associated with this session'}), 400

        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        if not os.path.exists(json_filepath):
            return jsonify({'error': 'ProSiT parameter file not found'}), 404

        with open(json_filepath, 'r') as f:
            prosit_json = json.load(f)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(prosit_json, f, indent=4)
            temp_path = f.name

        return send_file(
            temp_path,
            as_attachment=True,
            download_name=f'prosit_parameters_{session_id}.json',
            mimetype='application/json',
        )

    except Exception as e:
        logger.error(f"Export parameters error: {e}")
        return jsonify({'error': str(e)}), 500
