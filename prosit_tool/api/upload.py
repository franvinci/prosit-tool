"""Upload endpoint: accept XES or CSV (and optional PNML), create a SimulationSession."""

import os
import shutil
import logging

import pandas as pd
import pm4py
from flask import Blueprint, current_app, request, jsonify
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import SimulationSession
from ..validators import validate_noise_threshold

from ._decorators import handle_api_errors
from ._shared import unique_timestamp

logger = logging.getLogger(__name__)
bp = Blueprint('upload', __name__)


# The optional roles of the mapping and the column each one becomes.
_OPTIONAL_COLUMNS = {'start_ts': 'start:timestamp', 'resource': 'org:resource'}


def _apply_mapping(df: pd.DataFrame, mapping: dict, source_label: str, unused=()) -> pd.DataFrame:
    """Rename DataFrame columns to pm4py conventions and check the required ones.

    Case id, activity and end timestamp are required. The start timestamp and
    the resource are optional and nothing is made up for them here: an event
    without them is written without them, and the reader of the log
    (``normalize_event_log``) decides what to use instead and tells the user.

    ``unused`` names the optional roles the user chose to leave out: a column
    of the log that already has the standard name of one of them is dropped,
    instead of being used behind the user's back.

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
    left_out = [_OPTIONAL_COLUMNS[role] for role in unused
                if not mapping.get(role) and _OPTIONAL_COLUMNS[role] in df.columns]
    if left_out:
        df = df.drop(columns=left_out)

    for column, meaning in (('case:concept:name', 'case id'), ('concept:name', 'activity'),
                            ('time:timestamp', 'end timestamp')):
        empty = int(df[column].isna().sum())
        if empty:
            raise ValueError(f"{source_label} has {empty} row(s) with no {meaning}")

    df['case:concept:name'] = df['case:concept:name'].astype(str)
    df['time:timestamp'] = pd.to_datetime(df['time:timestamp'], utc=True, errors='raise')
    if 'start:timestamp' in df.columns:
        df['start:timestamp'] = pd.to_datetime(df['start:timestamp'], utc=True, errors='raise')
        began = df['start:timestamp'].fillna(df['time:timestamp'])
    else:
        began = df['time:timestamp']

    # Events of a case in the order they started (an event with no start
    # timestamp is placed by its end).
    order = df.assign(_began=began).sort_values(
        by=['case:concept:name', '_began', 'time:timestamp'], kind='stable',
    ).index
    return df.loc[order].reset_index(drop=True)


def _write_xes(df: pd.DataFrame, xes_path: str) -> None:
    """Write the log, leaving out the attributes an event has no value for.

    Written as they are, the empty cells of a table would become attributes
    whose value is the text "nan".

    Timestamps are written to the microsecond. A table can carry nanoseconds,
    but a timestamp with nine decimals is one that pm4py cannot read back on
    Python 3.10: the events would come back without a timestamp.
    """
    df = df.copy()
    for column in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            df[column] = df[column].dt.floor('us')
    pm4py.write_xes(pm4py.convert_to_event_log(df, stream_postprocessing=True), xes_path)


def _csv_to_xes(csv_path: str, xes_path: str, mapping: dict, unused=()) -> None:
    """Read a CSV log, rename columns to pm4py conventions, write as XES."""
    df = pd.read_csv(csv_path)
    df = _apply_mapping(df, mapping, source_label='CSV', unused=unused)
    _write_xes(df, xes_path)


_DEFAULT_XES_COLS = {
    'case_id': 'case:concept:name',
    'activity': 'concept:name',
    'end_ts': 'time:timestamp',
    'start_ts': 'start:timestamp',
    'resource': 'org:resource',
}


def _xes_apply_mapping(input_xes_path: str, output_xes_path: str, mapping: dict, unused=()) -> None:
    """If ``mapping`` is a no-op vs pm4py defaults, copy the XES; otherwise
    re-read with pm4py, rename columns, and write a new XES."""
    is_noop = not unused and all(
        mapping.get(k) in (None, '', _DEFAULT_XES_COLS[k]) for k in _DEFAULT_XES_COLS
    )
    if is_noop:
        if os.path.abspath(input_xes_path) != os.path.abspath(output_xes_path):
            shutil.copyfile(input_xes_path, output_xes_path)
        return

    df = pm4py.convert_to_dataframe(pm4py.read_xes(input_xes_path))
    df = _apply_mapping(df, mapping, source_label='XES', unused=unused)
    _write_xes(df, output_xes_path)


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

    # Where the Petri net comes from, as chosen in the form. A client that
    # does not say (the field is the form's) imports the net it sends, if any.
    net_source = (request.form.get('petriNetSource') or '').strip().lower()
    if net_source not in ('', 'discover', 'import'):
        return jsonify({'error': "petriNetSource must be 'discover' or 'import'"}), 400
    if net_source == 'discover':
        pnml_file = None  # whatever file came along is not what was asked for
    elif net_source == 'import' and not (pnml_file and pnml_file.filename):
        return jsonify({'error': 'Choose the PNML file of the Petri net to import'}), 400

    if pnml_file and pnml_file.filename and not pnml_file.filename.lower().endswith('.pnml'):
        return jsonify({'error': 'PNML file must have .pnml extension'}), 400

    timestamp = unique_timestamp()

    case_id_col = (request.form.get('case_id_col') or '').strip()
    activity_col = (request.form.get('activity_col') or '').strip()
    end_ts_col = (request.form.get('end_ts_col') or '').strip()
    start_ts_col = (request.form.get('start_ts_col') or '').strip()
    resource_col = (request.form.get('resource_col') or '').strip()
    has_mapping = bool(case_id_col or activity_col or end_ts_col or start_ts_col or resource_col)

    if is_csv and not has_mapping:
        return jsonify({'error': 'CSV upload requires column mapping'}), 400

    if has_mapping:
        # The start timestamp and the resource are optional (see _apply_mapping).
        missing = [k for k, v in (
            ('case_id_col', case_id_col),
            ('activity_col', activity_col),
            ('end_ts_col', end_ts_col),
        ) if not v]
        if missing:
            return jsonify({'error': f"Column mapping incomplete: {', '.join(missing)}"}), 400

    # "(none)" chosen for an optional column: the field is sent, and is empty.
    unused = [role for role, field in (('start_ts', 'start_ts_col'), ('resource', 'resource_col'))
              if has_mapping and field in request.form and not request.form[field].strip()]

    mapping = {
        'case_id': case_id_col,
        'activity': activity_col,
        'end_ts': end_ts_col,
        'start_ts': start_ts_col,
        'resource': resource_col,
    }

    base = os.path.splitext(secure_filename(xes_file.filename))[0]
    xes_filename = f"{timestamp}_{base}.xes"
    xes_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], xes_filename)

    if is_csv:
        csv_filename = f"{timestamp}_{secure_filename(xes_file.filename)}"
        csv_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], csv_filename)
        xes_file.save(csv_filepath)
        try:
            _csv_to_xes(csv_filepath, xes_filepath, mapping, unused)
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
        original_xes_path = os.path.join(current_app.config['UPLOAD_FOLDER'], original_xes_filename)
        xes_file.save(original_xes_path)
        try:
            if has_mapping:
                _xes_apply_mapping(original_xes_path, xes_filepath, mapping, unused)
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
        pnml_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], pnml_filename)
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
