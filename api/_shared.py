"""Helpers shared across multiple API blueprints."""

import os
import logging

import pm4py
from pm4py.objects.log.importer.xes import importer as xes_importer

from app import app
from prosit_integration import ProSiTIntegration

logger = logging.getLogger(__name__)


def load_session_prosit(session, *, with_event_log=False, compute_metrics=False):
    """Build a fresh ProSiTIntegration for a session.

    Replays the saved Petri net (PNML) and optionally re-imports the XES event
    log. Replaces the previous global singleton — every request gets its own
    isolated instance, eliminating cross-request state leaks.
    """
    metadata = session.get_parameters() or {}
    pnml_filename = metadata.get('pnml_filename')
    if not pnml_filename:
        raise FileNotFoundError(
            'No Petri net (PNML) is associated with this session. Run discovery first.'
        )

    pnml_path = os.path.join(app.config['UPLOAD_FOLDER'], pnml_filename)
    if not os.path.exists(pnml_path):
        raise FileNotFoundError(f'PNML file not found: {pnml_filename}')

    instance = ProSiTIntegration()
    if with_event_log:
        xes_path = os.path.join(app.config['UPLOAD_FOLDER'], session.filename)
        if not os.path.exists(xes_path):
            raise FileNotFoundError(f'XES file not found: {session.filename}')
        instance.event_log = xes_importer.apply(xes_path)

    instance.import_petri_net_from_pnml(pnml_path, compute_metrics=compute_metrics)
    return instance


def save_petri_net_pnml(net, initial_marking, final_marking, session_id, timestamp):
    """Persist a Petri net to disk under uploads/ and return its filename."""
    pnml_filename = f"{timestamp}_{session_id}_model.pnml"
    pnml_path = os.path.join(app.config['UPLOAD_FOLDER'], pnml_filename)
    pm4py.write_pnml(net, initial_marking, final_marking, pnml_path)
    return pnml_filename
