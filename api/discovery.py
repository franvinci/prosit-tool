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
    validate_grace_period,
    validate_max_depth_tree,
    validate_multitasking_thr,
    validate_random_state,
)

from ._shared import save_petri_net_pnml

logger = logging.getLogger(__name__)
bp = Blueprint('discovery', __name__)


@bp.route('/api/discover/<int:session_id>', methods=['POST'])
def discover_parameters(session_id):
    """Discover parameters from uploaded file (XES or PNML)."""
    session = SimulationSession.query.get_or_404(session_id)
    try:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], session.filename)
        if not os.path.exists(filepath):
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
        attribute_mode = request.args.get('attribute_mode', Config.DEFAULT_ATTRIBUTE_MODE)

        existing_metadata = session.get_parameters() or {}
        pnml_filepath = None
        if 'pnml_filename' in existing_metadata:
            pnml_filepath = os.path.join(app.config['UPLOAD_FOLDER'], existing_metadata['pnml_filename'])

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
            prosit.import_petri_net_from_pnml(pnml_filepath)
        else:
            logger.info("Discovering process model and parameters from XES")
            prosit.discover_process_model(noise_threshold=session.noise_threshold)
        process_model = prosit.process_model
        parameters = prosit.discover_parameters(**discovery_kwargs)
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
                'fitness': process_model.get('fitness', 0),
                'precision': process_model.get('precision', 0),
                'f_measure': process_model.get('f_measure', 0),
            },
            'prosit_metrics': prosit_metrics,
            'message': 'Parameters processed successfully',
        })

    except Exception as e:
        logger.error(f"Discovery error: {e}")
        db.session.rollback()
        try:
            session = SimulationSession.query.get(session_id)
            if session:
                session.status = 'error'
                db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'error': f'Parameter discovery failed: {e}'}), 500
