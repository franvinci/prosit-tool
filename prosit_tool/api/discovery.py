"""Discovery endpoint: run Petri net + parameter discovery from a session's XES."""

import os
import logging

from flask import Blueprint, current_app, request, jsonify

from .. import progress
from ..extensions import db
from ..models import BASELINE_RUN_NAME, SimulationRun, SimulationSession
from ..prosit_integration import (
    LIBRARY_STEPS,
    DiscoveryError,
    ModelMismatchError,
    ProSiTIntegration,
    discovery_steps,
)
from ..validators import validate_discovery_options

from ._decorators import handle_api_errors
from ._shared import (
    MODEL_METRICS,
    EventLogError,
    load_event_log,
    load_session_prosit,
    remove_file,
    save_petri_net_pnml,
    unique_timestamp,
)

logger = logging.getLogger(__name__)
bp = Blueprint('discovery', __name__)


def _progress_key(session_id: int) -> str:
    """Under which name the progress of a session's discovery is followed."""
    return f'discovery:{session_id}'


def _mark_session_failed(session_id: int) -> None:
    """Roll back the current transaction and flag the session as 'error'."""
    db.session.rollback()
    try:
        session = db.session.get(SimulationSession, session_id)
        if session:
            session.status = 'error'
            db.session.commit()
    except Exception:
        db.session.rollback()


@bp.route('/api/discover/<int:session_id>', methods=['POST'])
@handle_api_errors('Parameter discovery failed')
def discover_parameters(session_id):
    """Discover parameters from uploaded file (XES or PNML)."""
    session = db.get_or_404(SimulationSession, session_id)

    options, error = validate_discovery_options(request.args)
    if error:
        return jsonify({'error': error}), 400

    upload_folder = current_app.config['UPLOAD_FOLDER']
    filepath = os.path.join(upload_folder, session.filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404

    pnml_filename = (session.get_parameters() or {}).get('pnml_filename')
    if not (pnml_filename and os.path.exists(os.path.join(upload_folder, pnml_filename))):
        pnml_filename = None  # the model is discovered from the log

    steps = discovery_steps(
        importing_model=pnml_filename is not None,
        rules=options['max_depth_tree'] > 0,
        incremental=options['incremental_discovery'],
    )
    # While this runs, GET .../progress says which step it is at and how far.
    with progress.track(_progress_key(session_id), steps, LIBRARY_STEPS) as report:
        return _discover(session, filepath, pnml_filename, options, report)


def _discover(session, filepath, pnml_filename, options, report):
    """Run the discovery of a session and store what it finds; returns the response."""
    session_id = session.id
    upload_folder = current_app.config['UPLOAD_FOLDER']
    pnml_on_disk = pnml_filename is not None

    # Files written by this request; removed again if it does not complete.
    created = []
    try:
        session.status = 'discovering'
        db.session.commit()

        logger.info(f"Discovering parameters from XES file for session {session_id}")

        report.start('log')
        event_log, log_notes = load_event_log(filepath)
        logger.info(f"Loaded {len(event_log)} traces from XES file")

        # It announces the steps it runs itself; the ones of prosit-pm are
        # read from what the library prints.
        prosit = ProSiTIntegration(progress=report)
        prosit.event_log = event_log

        if pnml_on_disk:
            logger.info("Using PNML model and discovering parameters from XES")
            prosit.import_petri_net_from_pnml(os.path.join(upload_folder, pnml_filename))
        else:
            logger.info("Discovering process model and parameters from XES")
            prosit.discover_process_model(noise_threshold=session.noise_threshold)
        process_model = prosit.process_model
        parameters = prosit.discover_parameters(**options)
        report.start('saving')
        prosit_metrics = prosit.prosit_metrics or {}
        for metric_cat, metrics in prosit_metrics.items():
            for m, value in metrics.items():
                logger.info(f"Accuracy results for {m}: {value}")

        stamp = unique_timestamp()
        json_filename = f"{stamp}_s{session.id}_parameters.json"
        created.append(json_filename)
        prosit.save_parameters_to_json(os.path.join(upload_folder, json_filename))

        # Persist the Petri net so later endpoints can rebuild SimulatorParameters
        # without re-running discovery.
        if not pnml_on_disk:
            pnml_filename = f"{stamp}_{session.id}_model.pnml"
            created.append(pnml_filename)
            save_petri_net_pnml(
                process_model['net'], process_model['initial_marking'],
                process_model['final_marking'], pnml_filename,
            )

        # What cannot be read back from the PNML: how well the net fits the
        # log. Everything else about the model is derived from the net itself
        # whenever the session is opened.
        model_payload = {key: process_model.get(key, 0) for key in MODEL_METRICS}
        session_metadata = session.get_parameters() or {}
        session_metadata.update({
            'json_filename': json_filename,
            'pnml_filename': pnml_filename,
            'process_model': model_payload,
            'prosit_metrics': prosit_metrics,
        })
        session.set_parameters(session_metadata)
        session.status = 'ready'
        session.touch()

        # Create (or refresh) the As-Is baseline run that points at the
        # discovered JSON. Re-running discovery on a session resets the
        # baseline; user-created what-if runs are kept untouched.
        baseline = session.get_baseline_run()
        replaced_parameters = replaced_simulation = None
        if baseline is None:
            baseline = SimulationRun(
                session_id=session.id,
                name=BASELINE_RUN_NAME,
                is_baseline=True,
            )
            db.session.add(baseline)
        else:
            replaced_parameters = baseline.parameters_filename
            replaced_simulation = baseline.simulation_df_filename
        baseline.parameters_filename = json_filename
        baseline.simulation_df_filename = None  # invalidate any stale sim
        baseline.num_instances = None
        baseline.last_run_at = None

        db.session.commit()

    except (EventLogError, DiscoveryError) as exc:
        # The request was fine but nothing can be learnt from this log or
        # model: tell the user why instead of a bare 500.
        for filename in created:
            remove_file(upload_folder, filename)
        _mark_session_failed(session_id)
        if isinstance(exc, EventLogError):
            reason = 'The event log cannot be used.'
        elif isinstance(exc, ModelMismatchError):
            reason = 'The Petri net cannot be used with this event log.'
        else:
            reason = 'Parameter discovery failed.'
        return jsonify({'error': f'{reason} {exc}'}), 422

    except Exception:
        for filename in created:
            remove_file(upload_folder, filename)
        _mark_session_failed(session_id)
        raise  # let @handle_api_errors produce the JSON response

    # The previous discovery of this session is now unreachable: drop its files,
    # unless a what-if run still points at them.
    still_used = {run.parameters_filename for run in session.runs}
    if replaced_parameters and replaced_parameters not in still_used:
        remove_file(upload_folder, replaced_parameters)
    remove_file(current_app.config['SIMULATION_FOLDER'], replaced_simulation)

    return jsonify({
        'success': True,
        'parameters': parameters,
        'json_filename': json_filename,
        'process_model': parameters['process_model'],
        'prosit_metrics': prosit_metrics,
        'warnings': log_notes + list(prosit.model_warnings) + list(prosit.discovery_warnings),
        'message': 'Parameters processed successfully',
    })


@bp.route('/api/discover/<int:session_id>/progress')
def discover_progress(session_id):
    """How far the discovery of a session has got.

    ``in_progress`` is false when none is running. Otherwise: ``percent`` of
    the whole, the ``step`` in progress out of ``steps`` and its ``label``,
    and, when the step counts what it does, ``done`` of ``total`` ``unit``.
    """
    report = progress.snapshot(_progress_key(session_id)) or {'in_progress': False, 'message': ''}
    response = jsonify(report)
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/api/metrics/<int:session_id>', methods=['POST'])
@handle_api_errors('Failed to compute metrics')
def compute_metrics(session_id):
    """Run a reference simulation matched to the original log and evaluate.

    Discovery skips this step by default to keep the request fast; the UI
    fires this endpoint asynchronously to fill in the accuracy tables.
    """
    session = db.get_or_404(SimulationSession, session_id)
    metadata = session.get_parameters() or {}
    json_filename = metadata.get('json_filename')
    if not json_filename:
        return jsonify({'error': 'No discovered parameters; run discovery first'}), 400

    json_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], json_filename)
    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Parameter file missing'}), 404

    prosit = load_session_prosit(session, with_event_log=True)
    prosit.load_parameters_from_json_file(json_filepath)
    metrics = prosit.compute_prosit_metrics()

    metadata['prosit_metrics'] = metrics
    session.set_parameters(metadata)
    db.session.commit()

    return jsonify({'success': True, 'prosit_metrics': metrics})
