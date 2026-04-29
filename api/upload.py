"""Upload endpoint: accept XES (and optional PNML), create a SimulationSession."""

import os
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from app import app, db
from models import SimulationSession
from validators import validate_noise_threshold

from ._decorators import handle_api_errors

logger = logging.getLogger(__name__)
bp = Blueprint('upload', __name__)


@bp.route('/api/upload', methods=['POST'])
@handle_api_errors('Upload failed')
def upload_file():
    """Handle XES file upload with optional PNML file."""
    if 'xes_file' not in request.files:
        return jsonify({'error': 'No XES file provided'}), 400

    xes_file = request.files['xes_file']
    pnml_file = request.files.get('pnml_file')
    noise_threshold, err = validate_noise_threshold(request.form.get('noise_threshold'))
    if err:
        return jsonify({'error': err}), 400

    if not xes_file.filename:
        return jsonify({'error': 'No XES file selected'}), 400

    if not xes_file.filename.lower().endswith('.xes'):
        return jsonify({'error': 'XES file must have .xes extension'}), 400

    if pnml_file and pnml_file.filename and not pnml_file.filename.lower().endswith('.pnml'):
        return jsonify({'error': 'PNML file must have .pnml extension'}), 400

    xes_filename = secure_filename(xes_file.filename)
    timestamp = int(datetime.now().timestamp())
    xes_filename = f"{timestamp}_{xes_filename}"
    xes_filepath = os.path.join(app.config['UPLOAD_FOLDER'], xes_filename)
    xes_file.save(xes_filepath)

    pnml_filename = None
    if pnml_file and pnml_file.filename:
        pnml_filename = secure_filename(pnml_file.filename)
        pnml_filename = f"{timestamp}_{pnml_filename}"
        pnml_filepath = os.path.join(app.config['UPLOAD_FOLDER'], pnml_filename)
        pnml_file.save(pnml_filepath)

    session = SimulationSession(
        filename=xes_filename,
        noise_threshold=noise_threshold,
    )
    if pnml_filename:
        session.set_parameters({'pnml_filename': pnml_filename})

    db.session.add(session)
    db.session.commit()

    logger.info(f"Files uploaded successfully: XES={xes_filename}, PNML={pnml_filename}")
    return jsonify({
        'success': True,
        'session_id': session.id,
        'filename': xes_filename,
        'pnml_filename': pnml_filename,
        'message': 'Files uploaded successfully',
    })
