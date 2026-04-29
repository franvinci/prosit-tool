"""Discovery endpoint: run Petri net + parameter discovery from a session's XES."""

import os
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify
from pm4py.objects.log.importer.xes import importer as xes_importer

from app import app, db
from config import Config
from models import SimulationSession
from prosit_integration import ProSiTIntegration
from validators import (
    parse_bool,
    validate_attribute_mode,
    validate_grace_period,
    validate_max_depth_tree,
    validate_multitasking_thr,
    validate_random_state,
)

from ._decorators import handle_api_errors
from ._shared import load_session_prosit, save_petri_net_pnml

logger = logging.getLogger(__name__)
bp = Blueprint('discovery', __name__)


# Tracks the human-readable phase of an in-flight discovery request so the UI
# can poll and surface progress under the loading spinner. Single-process
# only — that's fine for this dev tool.
_discovery_progress: dict[int, str] = {}


def _set_progress(session_id: int, message: str) -> None:
    _discovery_progress[session_id] = message


def _clear_progress(session_id: int) -> None:
    _discovery_progress.pop(session_id, None)


@bp.route('/api/discover/<int:session_id>', methods=['POST'])
@handle_api_errors('Parameter discovery failed')
def discover_parameters(session_id):
    """Discover parameters from uploaded file (XES or PNML)."""
    session = SimulationSession.query.get_or_404(session_id)
    try:
        _set_progress(session_id, 'Preparing discovery...')
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], session.filename)
        if not os.path.exists(filepath):
            _clear_progress(session_id)
            return jsonify({'error': 'File not found'}), 404

        session.status = 'discovering'
        db.session.commit()

        logger.info(f"Discovering parameters from XES file for session {session_id}")

        max_depth_tree, _ = validate_max_depth_tree(request.args.get('max_depth_tree'))
        grace_period, _ = validate_grace_period(request.args.get('grace_period'))
        multitasking_thr, _ = validate_multitasking_thr(request.args.get('multitasking_thr'))
        random_state, _ = validate_random_state(request.args.get('random_state'))
        incremental_discovery = parse_bool(request.args.get('incremental_discovery'))
        enable_multitasking = parse_bool(request.args.get('enable_multitasking'))
        use_workload_features = parse_bool(request.args.get('use_workload_features'))
        attribute_mode, _ = validate_attribute_mode(request.args.get('attribute_mode'))

        existing_metadata = session.get_parameters() or {}
        pnml_filepath = None
        if 'pnml_filename' in existing_metadata:
            pnml_filepath = os.path.join(app.config['UPLOAD_FOLDER'], existing_metadata['pnml_filename'])

        _set_progress(session_id, 'Loading event log...')
        event_log = xes_importer.apply(filepath)
        logger.info(f"Loaded {len(event_log)} traces from XES file")

        prosit = ProSiTIntegration()
        prosit.event_log = event_log

        discovery_kwargs = dict(
            max_depth_tree=max_depth_tree,
            incremental_discovery=incremental_discovery,
            grace_period=grace_period,
            enable_multitasking=enable_multitasking,
            multitasking_thr=multitasking_thr,
            random_state=random_state,
            use_workload_features=use_workload_features,
            attribute_mode=attribute_mode,
        )

        if pnml_filepath and os.path.exists(pnml_filepath):
            logger.info("Using PNML model and discovering parameters from XES")
            _set_progress(session_id, 'Loading uploaded Petri net...')
            prosit.import_petri_net_from_pnml(pnml_filepath)
        else:
            logger.info("Discovering process model and parameters from XES")
            _set_progress(session_id, 'Discovering process model (Inductive Miner)...')
            prosit.discover_process_model(noise_threshold=session.noise_threshold)
        process_model = prosit.process_model
        _set_progress(session_id, 'Discovering simulation parameters (resources, times, attributes)...')
        parameters = prosit.discover_parameters(**discovery_kwargs)
        _set_progress(session_id, 'Saving parameters...')
        prosit_metrics = prosit.prosit_metrics or {}
        for metric_cat, metrics in prosit_metrics.items():
            for m, value in metrics.items():
                logger.info(f"Accuracy results for {m}: {value}")

        timestamp = int(datetime.now().timestamp())
        json_filename = f"{timestamp}_parameters.json"
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        prosit.save_parameters_to_json(json_filepath)

        # Persist the Petri net so later endpoints can rebuild SimulatorParameters
        # without re-running discovery.
        pnml_filename = existing_metadata.get('pnml_filename')
        if not pnml_filename:
            pnml_filename = save_petri_net_pnml(
                process_model['net'], process_model['initial_marking'],
                process_model['final_marking'], session.id, timestamp,
            )

        session_metadata = session.get_parameters() or {}
        session_metadata.update({
            'json_filename': json_filename,
            'pnml_filename': pnml_filename,
            'process_model': {
                'visualization': process_model.get('visualization'),
                'activities': process_model.get('activities', []),
                'transitions': process_model.get('transitions', []),
                'map_transitionName_to_id': process_model.get('map_transitionName_to_id', {}),
                'transition_label_map': process_model.get('transition_label_map', {}),
                'places': process_model.get('places', []),
                'fitness': process_model.get('fitness', 0),
                'precision': process_model.get('precision', 0),
                'f_measure': process_model.get('f_measure', 0),
            },
            'prosit_metrics': prosit_metrics,
        })
        session.set_parameters(session_metadata)
        session.status = 'ready'
        db.session.commit()
        _clear_progress(session_id)

        return jsonify({
            'success': True,
            'parameters': parameters,
            'json_filename': json_filename,
            'process_model': {
                'visualization': process_model.get('visualization'),
                'activities': process_model.get('activities', []),
                'transitions': process_model.get('transitions', []),
                'places': process_model.get('places', []),
                'map_transitionName_to_id': process_model.get('map_transitionName_to_id', {}),
                'transition_label_map': process_model.get('transition_label_map', {}),
                'fitness': process_model.get('fitness', 0),
                'precision': process_model.get('precision', 0),
                'f_measure': process_model.get('f_measure', 0),
            },
            'prosit_metrics': prosit_metrics,
            'message': 'Parameters processed successfully',
        })

    except Exception:
        db.session.rollback()
        try:
            session = SimulationSession.query.get(session_id)
            if session:
                session.status = 'error'
                db.session.commit()
        except Exception:
            db.session.rollback()
        _clear_progress(session_id)
        raise  # let @handle_api_errors produce the JSON response


@bp.route('/api/discover/<int:session_id>/progress')
def discover_progress(session_id):
    """Return the current discovery phase string, or empty if no work in flight."""
    message = _discovery_progress.get(session_id)
    return jsonify({'in_progress': message is not None, 'message': message or ''})


@bp.route('/api/metrics/<int:session_id>', methods=['POST'])
@handle_api_errors('Failed to compute metrics')
def compute_metrics(session_id):
    """Run a reference simulation matched to the original log and evaluate.

    Discovery skips this step by default to keep the request fast; the UI
    fires this endpoint asynchronously to fill in the accuracy tables.
    """
    session = SimulationSession.query.get_or_404(session_id)
    metadata = session.get_parameters() or {}
    json_filename = metadata.get('json_filename')
    if not json_filename:
        return jsonify({'error': 'No discovered parameters; run discovery first'}), 400

    json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Parameter file missing'}), 404

    prosit = load_session_prosit(session, with_event_log=True)
    prosit.load_parameters_from_json_file(json_filepath)
    metrics = prosit.compute_prosit_metrics()

    metadata['prosit_metrics'] = metrics
    session.set_parameters(metadata)
    db.session.commit()

    return jsonify({'success': True, 'prosit_metrics': metrics})
