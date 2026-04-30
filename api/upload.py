"""Upload endpoint: accept XES or CSV (and optional PNML), create a SimulationSession."""

import os
import shutil
import logging
from datetime import datetime

import pandas as pd
import pm4py
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from app import app, db
from models import SimulationSession
from validators import validate_noise_threshold

from ._decorators import handle_api_errors

logger = logging.getLogger(__name__)
bp = Blueprint('upload', __name__)


def _apply_mapping(df: pd.DataFrame, mapping: dict, source_label: str) -> pd.DataFrame:
    """Rename DataFrame columns to pm4py conventions and ensure required fields.

    ``source_label`` is used in error messages (e.g. ``"CSV"`` / ``"XES"``).
    """
    rename = {
        mapping['case_id']: 'case:concept:name',
        mapping['activity']: 'concept:name',
        mapping['end_ts']: 'time:timestamp',
    }
    if mapping.get('start_ts'):
        rename[mapping['start_ts']] = 'start:timestamp'
    if mapping.get('resource'):
        rename[mapping['resource']] = 'org:resource'

    missing = [src for src in rename.keys() if src not in df.columns]
    if missing:
        raise ValueError(f"{source_label} does not contain column(s): {', '.join(missing)}")

    # Avoid clobbering an existing destination column (e.g. mapping creates a
    # duplicate 'case:concept:name' if both old and new columns exist).
    drop_cols = [dst for src, dst in rename.items() if src != dst and dst in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)
    df = df.rename(columns=rename)

    df['case:concept:name'] = df['case:concept:name'].astype(str)
    df['time:timestamp'] = pd.to_datetime(df['time:timestamp'], utc=True, errors='raise')
    if 'start:timestamp' in df.columns:
        df['start:timestamp'] = pd.to_datetime(df['start:timestamp'], utc=True, errors='raise')
    else:
        df['start:timestamp'] = df['time:timestamp']
    if 'org:resource' not in df.columns:
        df['org:resource'] = 'unknown'

    return df.sort_values(
        by=['case:concept:name', 'start:timestamp', 'time:timestamp']
    ).reset_index(drop=True)


def _csv_to_xes(csv_path: str, xes_path: str, mapping: dict) -> None:
    """Read a CSV log, rename columns to pm4py conventions, write as XES."""
    df = pd.read_csv(csv_path)
    df = _apply_mapping(df, mapping, source_label='CSV')
    pm4py.write_xes(df, xes_path)


_DEFAULT_XES_COLS = {
    'case_id': 'case:concept:name',
    'activity': 'concept:name',
    'end_ts': 'time:timestamp',
    'start_ts': 'start:timestamp',
    'resource': 'org:resource',
}


def _xes_apply_mapping(input_xes_path: str, output_xes_path: str, mapping: dict) -> None:
    """If ``mapping`` is a no-op vs pm4py defaults, copy the XES; otherwise
    re-read with pm4py, rename columns, and write a new XES."""
    is_noop = all(
        mapping.get(k) in (None, '', _DEFAULT_XES_COLS[k]) for k in _DEFAULT_XES_COLS
    )
    if is_noop:
        if os.path.abspath(input_xes_path) != os.path.abspath(output_xes_path):
            shutil.copyfile(input_xes_path, output_xes_path)
        return

    df = pm4py.convert_to_dataframe(pm4py.read_xes(input_xes_path))
    df = _apply_mapping(df, mapping, source_label='XES')
    pm4py.write_xes(df, output_xes_path)


@bp.route('/api/upload', methods=['POST'])
@handle_api_errors('Upload failed')
def upload_file():
    """Handle event-log file upload (XES or CSV) with optional PNML file."""
    if 'xes_file' not in request.files:
        return jsonify({'error': 'No event log file provided'}), 400

    xes_file = request.files['xes_file']
    pnml_file = request.files.get('pnml_file')
    noise_threshold, err = validate_noise_threshold(request.form.get('noise_threshold'))
    if err:
        return jsonify({'error': err}), 400

    if not xes_file.filename:
        return jsonify({'error': 'No event log file selected'}), 400

    lower_name = xes_file.filename.lower()
    is_csv = lower_name.endswith('.csv')
    if not (lower_name.endswith('.xes') or is_csv):
        return jsonify({'error': 'Event log must have .xes or .csv extension'}), 400

    if pnml_file and pnml_file.filename and not pnml_file.filename.lower().endswith('.pnml'):
        return jsonify({'error': 'PNML file must have .pnml extension'}), 400

    timestamp = int(datetime.now().timestamp())

    case_id_col = (request.form.get('case_id_col') or '').strip()
    activity_col = (request.form.get('activity_col') or '').strip()
    end_ts_col = (request.form.get('end_ts_col') or '').strip()
    start_ts_col = (request.form.get('start_ts_col') or '').strip()
    resource_col = (request.form.get('resource_col') or '').strip()
    has_mapping = bool(case_id_col or activity_col or end_ts_col or start_ts_col or resource_col)

    if is_csv and not has_mapping:
        return jsonify({'error': 'CSV upload requires column mapping'}), 400

    if has_mapping:
        missing = [k for k, v in (
            ('case_id_col', case_id_col),
            ('activity_col', activity_col),
            ('end_ts_col', end_ts_col),
            ('start_ts_col', start_ts_col),
            ('resource_col', resource_col),
        ) if not v]
        if missing:
            return jsonify({'error': f"Column mapping incomplete: {', '.join(missing)}"}), 400

    mapping = {
        'case_id': case_id_col,
        'activity': activity_col,
        'end_ts': end_ts_col,
        'start_ts': start_ts_col,
        'resource': resource_col,
    }

    base = os.path.splitext(secure_filename(xes_file.filename))[0]
    xes_filename = f"{timestamp}_{base}.xes"
    xes_filepath = os.path.join(app.config['UPLOAD_FOLDER'], xes_filename)

    if is_csv:
        csv_filename = f"{timestamp}_{secure_filename(xes_file.filename)}"
        csv_filepath = os.path.join(app.config['UPLOAD_FOLDER'], csv_filename)
        xes_file.save(csv_filepath)
        try:
            _csv_to_xes(csv_filepath, xes_filepath, mapping)
        except (ValueError, pd.errors.ParserError) as ve:
            return jsonify({'error': str(ve)}), 400
        finally:
            try:
                os.unlink(csv_filepath)
            except OSError:
                pass
    else:
        # Save the uploaded XES first; if mapping changes columns, re-read and
        # re-write with renames applied.
        original_xes_filename = f"{timestamp}_orig_{secure_filename(xes_file.filename)}"
        original_xes_path = os.path.join(app.config['UPLOAD_FOLDER'], original_xes_filename)
        xes_file.save(original_xes_path)
        try:
            if has_mapping:
                _xes_apply_mapping(original_xes_path, xes_filepath, mapping)
            else:
                shutil.move(original_xes_path, xes_filepath)
                original_xes_path = None
        except (ValueError, pd.errors.ParserError) as ve:
            return jsonify({'error': str(ve)}), 400
        finally:
            if original_xes_path and os.path.exists(original_xes_path):
                try:
                    os.unlink(original_xes_path)
                except OSError:
                    pass

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
