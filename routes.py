import os
import json
import logging
import io
import tempfile
from datetime import datetime

from flask import render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

from app import app, db
from models import SimulationSession
from prosit_integration import ProSiTIntegration
from pm4py.objects.log.importer.xes import importer as xes_importer

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import pm4py
from pm4py.visualization.dfg.variants import performance as dfg_perf_visualizer


logger = logging.getLogger(__name__)
prosit = ProSiTIntegration()

def allowed_file(filename):
    """Check if uploaded file has allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['xes', 'pnml']

@app.route('/')
def index():
    """Main application page displaying recent simulation sessions."""
    sessions = SimulationSession.query.order_by(SimulationSession.created_at.desc()).limit(10).all()
    return render_template('index.html', sessions=sessions)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle XES file upload with optional PNML file"""
    try:
        if 'xes_file' not in request.files:
            return jsonify({'error': 'No XES file provided'}), 400
        
        xes_file = request.files['xes_file']
        pnml_file = request.files['pnml_file']
        noise_threshold = float(request.form.get('noise_threshold', 0.2))
        
        if xes_file.filename == '':
            return jsonify({'error': 'No XES file selected'}), 400
        
        if not xes_file.filename.lower().endswith('.xes'):
            return jsonify({'error': 'XES file must have .xes extension'}), 400
        
        if pnml_file and pnml_file.filename and not pnml_file.filename.lower().endswith('.pnml'):
            return jsonify({'error': 'PNML file must have .pnml extension'}), 400
        
        # Save XES file
        if xes_file.filename is None:
            return jsonify({'error': 'Invalid XES filename'}), 400
            
        xes_filename = secure_filename(xes_file.filename)
        timestamp = int(datetime.now().timestamp())
        xes_filename = f"{timestamp}_{xes_filename}"
        xes_filepath = os.path.join(app.config['UPLOAD_FOLDER'], xes_filename)
        xes_file.save(xes_filepath)
        
        # Save PNML file if provided
        pnml_filename = None
        if pnml_file and pnml_file.filename:
            pnml_filename = secure_filename(pnml_file.filename)
            pnml_filename = f"{timestamp}_{pnml_filename}"
            pnml_filepath = os.path.join(app.config['UPLOAD_FOLDER'], pnml_filename)
            pnml_file.save(pnml_filepath)
        
        # Create session
        session = SimulationSession(
            filename=xes_filename,
            noise_threshold=noise_threshold
        )
        # Store PNML filename if provided (we'll need to add this field to the model)
        if pnml_filename:
            # Store PNML filename in session parameters
            session.set_parameters({'pnml_filename': pnml_filename})
        
        db.session.add(session)
        db.session.commit()
        
        logger.info(f"Files uploaded successfully: XES={xes_filename}, PNML={pnml_filename}")
        return jsonify({
            'success': True,
            'session_id': session.id,
            'filename': xes_filename,
            'pnml_filename': pnml_filename,
            'message': 'Files uploaded successfully'
        })
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/api/discover/<int:session_id>', methods=['POST'])
def discover_parameters(session_id):
    """Discover parameters from uploaded file (XES or PNML)"""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], session.filename)
        
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        # Update status
        session.status = 'discovering'
        db.session.commit()
        
        # Always discover parameters from XES file
        logger.info(f"Discovering parameters from XES file for session {session_id}")
        
        # Get max_depth_tree parameter for decision tree depth
        try:
            max_depth_tree = int(request.args.get('max_depth_tree', 0))
        except Exception:
            max_depth_tree = 0
        if max_depth_tree < 0:
            max_depth_tree = 0
        if max_depth_tree > 5:
            max_depth_tree = 5
        # Get incremental discovery setting
        incremental_discovery = request.args.get('incremental_discovery', '0') in ['1', 'true', 'True']
        
        # Get grace period setting
        try:
            grace_period = int(request.args.get('grace_period', '1000'))
            if grace_period < 1:
                grace_period = 1000
        except (ValueError, TypeError):
            grace_period = 1000
        
        # Check if there's a separate PNML file for the Petri net model
        pnml_filepath = None
        session_params = session.get_parameters()
        if session_params and 'pnml_filename' in session_params:
            pnml_filepath = os.path.join(app.config['UPLOAD_FOLDER'], session_params['pnml_filename'])
        
        event_log = xes_importer.apply(filepath)
        prosit.event_log = event_log
        logger.info(f"Loaded {len(event_log)} traces from XES file")

        if pnml_filepath and os.path.exists(pnml_filepath):
            # Use imported PNML model but discover parameters from XES
            logger.info(f"Using PNML model and discovering parameters from XES")
            prosit.import_petri_net_from_pnml(pnml_filepath)
            process_model = prosit.process_model
            parameters = prosit.discover_parameters(max_depth_tree=max_depth_tree, incremental_discovery=incremental_discovery, grace_period=grace_period)
        else:
            # Standard workflow: discover both model and parameters from XES
            logger.info(f"Discovering process model and parameters from XES")
            prosit.discover_process_model(noise_threshold=session.noise_threshold)
            process_model = prosit.process_model
            parameters = prosit.discover_parameters(max_depth_tree=max_depth_tree, incremental_discovery=incremental_discovery, grace_period=grace_period)
            prosit_metrics = prosit.prosit_metrics
            for metric_cat in prosit_metrics:
                for m in prosit_metrics[metric_cat]:
                    logger.info(f"Accuracy results for {m}: {prosit_metrics[metric_cat][m]}")
        
        # Save parameters to JSON file
        timestamp = int(datetime.now().timestamp())
        json_filename = f"{timestamp}_parameters.json"
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        prosit.save_parameters_to_json(json_filepath)
        
        
        # Store metadata in session
        session.set_parameters({
            'json_filename': json_filename,
            'process_model': {
                'visualization': process_model.get('visualization'),
                'activities': process_model.get('activities', []),
                'transitions': process_model.get('transitions', []),
                'map_transitionName_to_id': process_model.get('map_transitionName_to_id', {}),
                'places': process_model.get('places', []),
                'fitness': process_model.get('fitness', 0),
                'precision': process_model.get('precision', 0),
                'f_measure': process_model.get('f_measure', 0)
            },
            'prosit_metrics': prosit_metrics
        })
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
                'f_measure': process_model.get('f_measure', 0)
            },
            'prosit_metrics': prosit_metrics,
            'message': 'Parameters processed successfully'
        })
        
    except Exception as e:
        logger.error(f"Discovery error: {str(e)}")
        db.session.rollback()
        try:
            session = SimulationSession.query.get(session_id)
            if session:
                session.status = 'error'
                db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'error': f'Parameter discovery failed: {str(e)}'}), 500

@app.route('/api/parameters/<int:session_id>')
def get_parameters(session_id):
    """Get parameters for a session"""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        session_metadata = session.get_parameters()
        
        if not session_metadata:
            return jsonify({'error': 'No session metadata found'}), 404
        
        # Check if we have a JSON file to load from
        json_filename = session_metadata.get('json_filename')
        if json_filename:
            json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
            if os.path.exists(json_filepath):
                # Load parameters from JSON file
                parameters = prosit.load_parameters_from_json_file(json_filepath)
                # Merge with process model info from metadata
                if 'process_model' in session_metadata:
                    parameters['process_model'].update(session_metadata['process_model'])
                if 'prosit_metrics' in session_metadata:
                    parameters['prosit_metrics'].update(session_metadata['prosit_metrics'])
                
                return jsonify({
                    'success': True,
                    'parameters': parameters,
                    'status': session.status,
                    'json_filename': json_filename
                })
        
        # Fallback to stored parameters (legacy)
        return jsonify({
            'success': True,
            'parameters': session_metadata,
            'status': session.status
        })
        
    except Exception as e:
        logger.error(f"Get parameters error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/parameters/<int:session_id>', methods=['PUT'])
def update_parameters(session_id):
    """Update parameters for a session and save to JSON"""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        session_metadata = session.get_parameters()
        
        new_parameters = request.get_json()
        if not new_parameters:
            return jsonify({'error': 'No parameters provided'}), 400
        
        # Get the JSON filename from session metadata
        json_filename = session_metadata.get('json_filename')
        if not json_filename:
            return jsonify({'error': 'No JSON file associated with this session'}), 400
        
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        
        # Load current JSON parameters
        if os.path.exists(json_filepath):
            with open(json_filepath, 'r') as f:
                prosit_json = json.load(f)
        else:
            return jsonify({'error': 'Parameter JSON file not found'}), 404
        
        # Convert app format back to ProSiT JSON format and update
        prosit_json = convert_app_to_prosit_format(new_parameters, prosit_json)
        
        # Save updated parameters back to JSON
        with open(json_filepath, 'w') as f:
            json.dump(prosit_json, f, indent=4)

        logger.info(f"Parameters updated for session {session_id} and saved to {json_filename}")
        return jsonify({
            'success': True,
            'message': 'Parameters updated successfully'
        })
        
    except Exception as e:
        logger.error(f"Update parameters error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def convert_app_to_prosit_format(app_params, prosit_json):
    """Convert application parameters back to ProSiT JSON format.
    
    Args:
        app_params: Parameters from the web application
        prosit_json: Existing ProSiT JSON structure to update
        
    Returns:
        Updated ProSiT JSON structure
    """
    try:
        logger.info("Converting app parameters to ProSiT format")
        
        # Helper: normalize one distribution object (UI shape) into ProSiT shape
        def _normalize_dist(dist_obj, leaf_value=None):
            if not isinstance(dist_obj, dict):
                return dist_obj
            dist_name = dist_obj.get('dist_name', 'expon')
            params_raw = dist_obj.get('params', {})
            result = {'dist_name': dist_name}
            if isinstance(params_raw, list):
                if dist_name == 'fixed':
                    value = params_raw[0] if params_raw else (leaf_value if leaf_value is not None else 1.0)
                    result['params'] = [value]
                    result['min_value'] = dist_obj.get('min_value', value)
                    result['max_value'] = dist_obj.get('max_value', value)
                    result['mean_value'] = dist_obj.get('mean_value', value)
                elif dist_name == 'norm':
                    mean = params_raw[0] if len(params_raw) > 0 else dist_obj.get('mean_value', leaf_value or 15.0)
                    std = params_raw[1] if len(params_raw) > 1 else 5.0
                    result['params'] = [mean, std]
                    result['min_value'] = dist_obj.get('min_value', 0.0)
                    result['max_value'] = dist_obj.get('max_value', 60.0)
                    result['mean_value'] = mean
                elif dist_name == 'expon':
                    loc = params_raw[0] if len(params_raw) > 0 else 0.0
                    scale = params_raw[1] if len(params_raw) > 1 else dist_obj.get('mean_value', leaf_value or 15.0)
                    result['params'] = [loc, scale]
                    result['min_value'] = dist_obj.get('min_value', 0.0)
                    result['max_value'] = dist_obj.get('max_value', 60.0)
                    result['mean_value'] = scale
                elif dist_name == 'uniform':
                    low = params_raw[0] if len(params_raw) > 0 else dist_obj.get('min_value', 0.0)
                    high = params_raw[1] if len(params_raw) > 1 else dist_obj.get('max_value', 60.0)
                    result['params'] = [low, high]
                    result['min_value'] = low
                    result['max_value'] = high
                    result['mean_value'] = (low + high) / 2.0
                return result

            # Object style params
            if isinstance(params_raw, dict):
                mean = params_raw.get('mean', dist_obj.get('mean_value', leaf_value or 15.0))
                std = params_raw.get('std', 5.0)
                min_v = params_raw.get('min', dist_obj.get('min_value', 0.0))
                max_v = params_raw.get('max', dist_obj.get('max_value', 60.0))
                fixed_v = params_raw.get('value', mean)
            else:
                mean, std, min_v, max_v, fixed_v = (leaf_value or 15.0), 5.0, 0.0, 60.0, (leaf_value or 15.0)

            if dist_name == 'fixed':
                result['params'] = [fixed_v]
                result['min_value'] = fixed_v
                result['max_value'] = fixed_v
                result['mean_value'] = fixed_v
            elif dist_name == 'norm':
                result['params'] = [mean, std]
                result['min_value'] = min_v
                result['max_value'] = max_v
                result['mean_value'] = mean
            elif dist_name == 'expon':
                result['params'] = [0.0, mean]
                result['min_value'] = min_v
                result['max_value'] = max_v
                result['mean_value'] = mean
            elif dist_name == 'uniform':
                result['params'] = [min_v, max_v]
                result['min_value'] = min_v
                result['max_value'] = max_v
                result['mean_value'] = (min_v + max_v) / 2.0
            return result

        def _transform_dist_tree(tree):
            """Normalize every leaf of a decision tree having shape like { '0': {...}, '1': {...} }"""
            if not isinstance(tree, dict):
                return tree
            normalized = {}
            for key, node in tree.items():
                if isinstance(node, dict) and 'value' in node:
                    leaf_value = node.get('value')
                    dist_obj = node.get('dist', {'dist_name': 'expon', 'params': {'mean': leaf_value if leaf_value is not None else 15.0}})
                    normalized[key] = {
                        'value': leaf_value,
                        'dist': _normalize_dist(dist_obj, leaf_value)
                    }
                elif isinstance(node, dict) and 'feature' in node:
                    normalized[key] = {
                        'feature': node.get('feature'),
                        'threshold': node.get('threshold'),
                        'children': node.get('children', {})
                    }
                else:
                    normalized[key] = node
            return normalized
        
        # Update transition weights
        if 'transition_params' in app_params and 'transition_weights' in app_params['transition_params']:
            prosit_json['transition_params']['transition_weights'] = app_params['transition_params']['transition_weights']
        
        # Update execution time parameters (supports tree or single distribution per activity)
        if 'execution_time_params' in app_params and 'activity_durations' in app_params['execution_time_params']:
            for activity, params in app_params['execution_time_params']['activity_durations'].items():
                # Decision tree case: object with keys '0', '1', ...
                if isinstance(params, dict) and '0' in params:
                    prosit_entry = _transform_dist_tree(params)
                else:
                    dist = params.get('distribution', 'fixed')
                    param_values = params.get('parameters', {})
                    
                    prosit_entry = {
                        'dist_name': dist,
                        'min_value': param_values.get('min', param_values.get('min_value', 1.0)),
                        'max_value': param_values.get('max', param_values.get('max_value', 1.0)),
                        'mean_value': param_values.get('mean', param_values.get('mean_value', 1.0))
                    }
                    
                    # Convert parameters based on distribution type, using actual values not defaults
                    if dist == 'fixed':
                        value = param_values.get('value', param_values.get('mean', param_values.get('mean_value', 1.0)))
                        prosit_entry['params'] = [value]
                        prosit_entry['min_value'] = value  # For fixed, min equals value
                        prosit_entry['max_value'] = value  # For fixed, max equals value
                        prosit_entry['mean_value'] = value
                    elif dist == 'norm':
                        prosit_entry['params'] = [
                            param_values.get('mean', param_values.get('mean_value', 15.0)),
                            param_values.get('std', 5.0)
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                    elif dist == 'expon':
                        prosit_entry['params'] = [
                            0.0,
                            param_values.get('mean', param_values.get('mean_value', 15.0))
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                    elif dist == 'uniform':
                        prosit_entry['params'] = [
                            param_values.get('min', param_values.get('min_value', 0.0)),
                            param_values.get('max', param_values.get('max_value', 60.0))
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 0.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = (param_values.get('min', param_values.get('min_value', 0.0)) + param_values.get('max', param_values.get('max_value', 60.0))) / 2
                
                prosit_json['execution_time_params']['execution_time_distributions'][activity] = prosit_entry
        
        # Update waiting time parameters (supports tree and non-tree; reads correct app key)
        if 'waiting_time_params' in app_params:
            # Prefer the new key used by the UI
            src = app_params['waiting_time_params'].get('resource_waiting_times') or app_params['waiting_time_params'].get('waiting_time') or {}
            for resource, params in src.items():
                if isinstance(params, dict) and '0' in params:
                    prosit_entry = _transform_dist_tree(params)
                else:
                    dist = params.get('distribution', 'fixed')
                    param_values = params.get('parameters', {})
                    
                    prosit_entry = {
                        'dist_name': dist,
                        'min_value': param_values.get('min', param_values.get('min_value', 1.0)),
                        'max_value': param_values.get('max', param_values.get('max_value', 1.0)),
                        'mean_value': param_values.get('mean', param_values.get('mean_value', 1.0))
                    }
                    
                    # Convert parameters based on distribution type, using actual values not defaults
                    if dist == 'fixed':
                        value = param_values.get('value', param_values.get('mean', param_values.get('mean_value', 1.0)))
                        prosit_entry['params'] = [value]
                        prosit_entry['min_value'] = value  # For fixed, min equals value
                        prosit_entry['max_value'] = value  # For fixed, max equals value
                        prosit_entry['mean_value'] = value
                    elif dist == 'norm':
                        prosit_entry['params'] = [
                            param_values.get('mean', param_values.get('mean_value', 15.0)),
                            param_values.get('std', 5.0)
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                    elif dist == 'expon':
                        prosit_entry['params'] = [
                            0.0,
                            param_values.get('mean', param_values.get('mean_value', 15.0))
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                    elif dist == 'uniform':
                        prosit_entry['params'] = [
                            param_values.get('min', param_values.get('min_value', 0.0)),
                            param_values.get('max', param_values.get('max_value', 60.0))
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 0.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = (param_values.get('min', param_values.get('min_value', 0.0)) + param_values.get('max', param_values.get('max_value', 60.0))) / 2
                
                prosit_json['waiting_time_params']['waiting_time_distributions'][resource] = prosit_entry
        
        # Update inter-arrival time parameters
        if 'inter_arrival_params' in app_params and 'inter_arrival_time' in app_params['inter_arrival_params']:
            inter_arrival = app_params['inter_arrival_params']['inter_arrival_time']

            def _normalize_dist(dist_obj, leaf_value=None):
                """Normalize a distribution object coming from the UI into ProSiT format."""
                if not isinstance(dist_obj, dict):
                    return dist_obj
                dist_name = dist_obj.get('dist_name', 'expon')
                params_raw = dist_obj.get('params', {})

                # If params is an array already and aligns with dist_name, keep but also compute helpers
                result = {
                    'dist_name': dist_name
                }
                # Extract typed params, supporting both array and object inputs
                if isinstance(params_raw, list):
                    if dist_name == 'fixed':
                        value = params_raw[0] if params_raw else (leaf_value if leaf_value is not None else 1.0)
                        result['params'] = [value]
                        result['min_value'] = dist_obj.get('min_value', value)
                        result['max_value'] = dist_obj.get('max_value', value)
                        result['mean_value'] = dist_obj.get('mean_value', value)
                    elif dist_name == 'norm':
                        mean = params_raw[0] if len(params_raw) > 0 else dist_obj.get('mean_value', leaf_value or 15.0)
                        std = params_raw[1] if len(params_raw) > 1 else 5.0
                        result['params'] = [mean, std]
                        result['min_value'] = dist_obj.get('min_value', 0.0)
                        result['max_value'] = dist_obj.get('max_value', 60.0)
                        result['mean_value'] = mean
                    elif dist_name == 'expon':
                        loc = params_raw[0] if len(params_raw) > 0 else 0.0
                        scale = params_raw[1] if len(params_raw) > 1 else dist_obj.get('mean_value', leaf_value or 15.0)
                        result['params'] = [loc, scale]
                        result['min_value'] = dist_obj.get('min_value', 0.0)
                        result['max_value'] = dist_obj.get('max_value', 60.0)
                        result['mean_value'] = scale
                    elif dist_name == 'uniform':
                        low = params_raw[0] if len(params_raw) > 0 else dist_obj.get('min_value', 0.0)
                        high = params_raw[1] if len(params_raw) > 1 else dist_obj.get('max_value', 60.0)
                        result['params'] = [low, high]
                        result['min_value'] = low
                        result['max_value'] = high
                        result['mean_value'] = (low + high) / 2.0
                    return result

                # Object style params coming from UI
                mean = params_raw.get('mean', dist_obj.get('mean_value', leaf_value or 15.0)) if isinstance(params_raw, dict) else (leaf_value or 15.0)
                std = params_raw.get('std', 5.0) if isinstance(params_raw, dict) else 5.0
                min_v = params_raw.get('min', dist_obj.get('min_value', 0.0)) if isinstance(params_raw, dict) else dist_obj.get('min_value', 0.0)
                max_v = params_raw.get('max', dist_obj.get('max_value', 60.0)) if isinstance(params_raw, dict) else dist_obj.get('max_value', 60.0)
                fixed_v = params_raw.get('value', mean) if isinstance(params_raw, dict) else mean

                if dist_name == 'fixed':
                    result['params'] = [fixed_v]
                    result['min_value'] = fixed_v
                    result['max_value'] = fixed_v
                    result['mean_value'] = fixed_v
                elif dist_name == 'norm':
                    result['params'] = [mean, std]
                    result['min_value'] = min_v
                    result['max_value'] = max_v
                    result['mean_value'] = mean
                elif dist_name == 'expon':
                    result['params'] = [0.0, mean]
                    result['min_value'] = min_v
                    result['max_value'] = max_v
                    result['mean_value'] = mean
                elif dist_name == 'uniform':
                    result['params'] = [min_v, max_v]
                    result['min_value'] = min_v
                    result['max_value'] = max_v
                    result['mean_value'] = (min_v + max_v) / 2.0
                return result

            def _transform_arrival_tree(tree):
                """Recursively normalize all leaves of an arrival-time decision tree."""
                if not isinstance(tree, dict):
                    return tree
                normalized = {}
                for key, node in tree.items():
                    if isinstance(node, dict) and 'value' in node:
                        # Leaf node
                        leaf_value = node.get('value')
                        dist_obj = node.get('dist', {'dist_name': 'expon', 'params': {'mean': leaf_value if leaf_value is not None else 15.0}})
                        normalized[key] = {
                            'value': leaf_value,
                            'dist': _normalize_dist(dist_obj, leaf_value)
                        }
                    elif isinstance(node, dict) and 'feature' in node:
                        # Split node
                        children = node.get('children', {})
                        normalized[key] = {
                            'feature': node.get('feature'),
                            'threshold': node.get('threshold'),
                            'children': children
                        }
                    else:
                        normalized[key] = node
                return normalized

            # If the UI stored a decision tree in `distribution`, normalize its leaves
            if isinstance(inter_arrival.get('distribution'), dict) and '0' in inter_arrival['distribution']:
                normalized_tree = _transform_arrival_tree(inter_arrival['distribution'])
                prosit_json['arrival_params']['arrival_time_distributions'] = normalized_tree
            else:
                # Non-tree case: single distribution object
                dist = inter_arrival.get('distribution', 'expon') if isinstance(inter_arrival, dict) else 'expon'
                param_values = inter_arrival.get('parameters', {}) if isinstance(inter_arrival, dict) else {}
                prosit_entry = {
                    'dist_name': dist,
                    'min_value': param_values.get('min', param_values.get('min_value', 1.0)),
                    'max_value': param_values.get('max', param_values.get('max_value', 1.0)),
                    'mean_value': param_values.get('mean', param_values.get('mean_value', 1.0))
                }
                if dist == 'fixed':
                    value = param_values.get('value', param_values.get('mean', param_values.get('mean_value', 1.0)))
                    prosit_entry['params'] = [value]
                    prosit_entry['min_value'] = value
                    prosit_entry['max_value'] = value
                    prosit_entry['mean_value'] = value
                elif dist == 'norm':
                    prosit_entry['params'] = [
                        param_values.get('mean', param_values.get('mean_value', 15.0)),
                        param_values.get('std', 5.0)
                    ]
                    prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                    prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                    prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                elif dist == 'expon':
                    prosit_entry['params'] = [
                        0.0,
                        param_values.get('mean', param_values.get('mean_value', 15.0))
                    ]
                    prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                    prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                    prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                elif dist == 'uniform':
                    prosit_entry['params'] = [
                        param_values.get('min', param_values.get('min_value', 0.0)),
                        param_values.get('max', param_values.get('max_value', 60.0))
                    ]
                    prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 0.0))
                    prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                    prosit_entry['mean_value'] = (param_values.get('min', param_values.get('min_value', 0.0)) + param_values.get('max', param_values.get('max_value', 60.0))) / 2
                prosit_json['arrival_params']['arrival_time_distributions'] = prosit_entry

            # Update arrival calendar if present
            if 'calendar' in inter_arrival:
                prosit_json['arrival_params']['arrival_calendar'] = inter_arrival['calendar']
        
        # Update resource parameters
        if 'resource_params' in app_params:
            resource_params = app_params['resource_params']
            
            # Update the main resources list first
            if 'resources' in resource_params:
                prosit_json['resource_params']['resources'] = resource_params['resources']
            
            # Ensure all resources are also added to specific parameter sections
            current_resources = set(prosit_json['resource_params'].get('resources', []))
            
            if 'resource_weights' in resource_params:
                prosit_json['resource_params']['resource_weights'] = resource_params['resource_weights']
                # Add any new resources from weights to the main list
                for resource in resource_params['resource_weights'].keys():
                    current_resources.add(resource)
            
            if 'multitasking_resource' in resource_params:
                prosit_json['resource_params']['multitasking_resource'] = resource_params['multitasking_resource']
            
            if 'act_to_resources' in resource_params:
                prosit_json['resource_params']['act_to_resources'] = resource_params['act_to_resources']
            
            if 'calendars' in resource_params:
                prosit_json['resource_params']['calendars'] = resource_params['calendars']
                # Add any new resources from calendars to the main list
                for resource in resource_params['calendars'].keys():
                    current_resources.add(resource)
            
            # Update the main resources list with all discovered resources
            prosit_json['resource_params']['resources'] = sorted(list(current_resources))
            
            # Ensure new resources have default parameters if missing
            for resource in current_resources:
                # Add default resource weight if missing
                if resource not in prosit_json['resource_params'].get('resource_weights', {}):
                    if 'resource_weights' not in prosit_json['resource_params']:
                        prosit_json['resource_params']['resource_weights'] = {}
                    prosit_json['resource_params']['resource_weights'][resource] = 0.1  # Default weight
                
                # Add default calendar if missing
                if resource not in prosit_json['resource_params'].get('calendars', {}):
                    if 'calendars' not in prosit_json['resource_params']:
                        prosit_json['resource_params']['calendars'] = {}
                    # Default 9-to-5 weekday calendar
                    prosit_json['resource_params']['calendars'][resource] = {
                        day: {str(hour): (9 <= hour <= 17) for hour in range(24)} 
                        for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    }
                
                # Add default waiting time distribution if missing
                if resource not in prosit_json.get('waiting_time_params', {}).get('waiting_time_distributions', {}):
                    if 'waiting_time_params' not in prosit_json:
                        prosit_json['waiting_time_params'] = {}
                    if 'waiting_time_distributions' not in prosit_json['waiting_time_params']:
                        prosit_json['waiting_time_params']['waiting_time_distributions'] = {}
                    # Default exponential waiting time distribution
                    prosit_json['waiting_time_params']['waiting_time_distributions'][resource] = {
                        'dist_name': 'fixed',
                        'params': [1.0],
                        'min_value': 1.0,
                        'max_value': 1.0,
                        'mean_value': 1.0
                    }

        # Update data attributes
        if 'data_attribute_params' in app_params:
            app_data_attrs = app_params['data_attribute_params']
            prosit_dist_attrs = {}
            categorical_attrs = app_data_attrs.get('label_data_attributes_categorical', [])

            for attr, params in app_data_attrs.get('distribution_data_attributes', {}).items():
                if attr in categorical_attrs:
                    prosit_dist_attrs[attr] = params
                else:
                    dist = params.get('distribution', 'fixed')
                    param_values = params.get('parameters', {})
                    
                    prosit_entry = {
                        'dist_name': dist,
                        'min_value': param_values.get('min', param_values.get('min_value', 1.0)),
                        'max_value': param_values.get('max', param_values.get('max_value', 1.0)),
                        'mean_value': param_values.get('mean', param_values.get('mean_value', 1.0))
                    }
                    
                    # Convert parameters based on distribution type, using actual values not defaults
                    if dist == 'fixed':
                        value = param_values.get('value', param_values.get('mean', param_values.get('mean_value', 1.0)))
                        prosit_entry['params'] = [value]
                        prosit_entry['min_value'] = value  # For fixed, min equals value
                        prosit_entry['max_value'] = value  # For fixed, max equals value
                        prosit_entry['mean_value'] = value
                    elif dist == 'norm':
                        prosit_entry['params'] = [
                            param_values.get('mean', param_values.get('mean_value', 15.0)),
                            param_values.get('std', 5.0)
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                    elif dist == 'expon':
                        prosit_entry['params'] = [
                            0.0,
                            param_values.get('mean', param_values.get('mean_value', 15.0))
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 1.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = param_values.get('mean', param_values.get('mean_value', 15.0))
                    elif dist == 'uniform':
                        prosit_entry['params'] = [
                            param_values.get('min', param_values.get('min_value', 0.0)),
                            param_values.get('max', param_values.get('max_value', 60.0))
                        ]
                        prosit_entry['min_value'] = param_values.get('min', param_values.get('min_value', 0.0))
                        prosit_entry['max_value'] = param_values.get('max', param_values.get('max_value', 60.0))
                        prosit_entry['mean_value'] = (param_values.get('min', param_values.get('min_value', 0.0)) + param_values.get('max', param_values.get('max_value', 60.0))) / 2
                    
                    prosit_dist_attrs[attr] = prosit_entry
            
            prosit_json['data_attribute_params']['distribution_data_attributes'] = prosit_dist_attrs
            prosit_json['data_attribute_params'].update({
                'label_data_attributes': app_data_attrs.get('label_data_attributes'),
                'label_data_attributes_categorical': app_data_attrs.get('label_data_attributes_categorical'),
                'attribute_values_label_categorical': app_data_attrs.get('attribute_values_label_categorical')
            })
        
        return prosit_json
        
    except Exception as e:
        logger.error(f"Error converting app to ProSiT format: {str(e)}")
        raise

@app.route('/api/load_test_json')
def load_test_json():
    """Load test JSON file for debugging"""
    try:
        json_path = os.path.join(app.config['UPLOAD_FOLDER'], 'test_params.json')
        if not os.path.exists(json_path):
            return jsonify({'error': 'Test JSON file not found'}), 404
        
        parameters = prosit.load_parameters_from_json_file(json_path)

        return jsonify({
            'success': True,
            'parameters': parameters,
            'message': 'Test JSON loaded successfully'
        })
        
    except Exception as e:
        logger.error(f"Error loading test JSON: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/simulate/<int:session_id>', methods=['POST'])
def simulate(session_id):
    """Generate simulated event log"""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        parameters = session.get_parameters()
        
        if not parameters:
            return jsonify({'error': 'No parameters found'}), 404
        
        request_data = request.get_json() or {}
        num_instances = int(request_data.get('num_instances', 100))
        if num_instances < 1 or num_instances > 10000:
            return jsonify({'error': 'Number of instances must be between 1 and 10000'}), 400
        
        # Update status
        session.status = 'simulating'
        db.session.commit()
        
        # Get start timestamp from request or use current time
        start_timestamp_str = request_data.get('start_timestamp')
        if start_timestamp_str:
            start_timestamp = datetime.fromisoformat(start_timestamp_str.replace('Z', '+00:00'))
        else:
            start_timestamp_str = str(datetime.now())
            start_timestamp = datetime.fromisoformat(start_timestamp_str.replace('Z', '+00:00'))
        
        # Load process model and run simulation using ProSiT
        logger.info(f"Starting simulation for session {session_id} with {num_instances} instances")
        
        # Load the stored modified parameters instead of rediscovering
        session_metadata = session.get_parameters()
        json_filename = session_metadata.get('json_filename')
        
        if not json_filename:
            return jsonify({'error': 'No stored parameters found for this session'}), 400
        
        # Get the path to the saved ProSiT JSON file (contains user modifications)
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        
        if not os.path.exists(json_filepath):
            return jsonify({'error': 'Stored parameter file not found'}), 404
        
        # Load the modified parameters from JSON instead of rediscovering
        logger.info(f"Using stored modified parameters from {json_filename}")
        prosit.load_parameters_from_json_file(json_filepath)
        
        # Run simulation using the modified parameters
        result_df = prosit.run_simulation(n_traces=num_instances, start_timestamp=start_timestamp)
        
        # Save simulation results
        timestamp = int(datetime.now().timestamp())
        output_filename = f'simulation_{timestamp}_{session_id}.csv'
        output_path = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result_df.to_csv(output_path, index=False)
        
        # Update status
        session.status = 'completed'
        session.simulation_df_filename = output_filename
        db.session.commit()
        
        return jsonify({
            'success': True,
            'sim_output_filename': output_filename,
            'num_events': len(result_df),
            'message': f'Simulation completed with {num_instances} instances, generated {len(result_df)} events'
        })
        
    except Exception as e:
        logger.error(f"Simulation error: {str(e)}")
        session = SimulationSession.query.get(session_id)
        if session:
            session.status = 'error'
            db.session.commit()
        return jsonify({'error': f'Simulation failed: {str(e)}'}), 500

@app.route('/api/download/<path:filename>')
def download_file(filename):
    """Download generated simulation file"""
    try:
        filepath = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(filepath, as_attachment=True)
        
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export_parameters/<int:session_id>')
def export_parameters(session_id):
    """Export parameters in ProSiT simulator format"""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        session_metadata = session.get_parameters()
        
        if not session_metadata:
            return jsonify({'error': 'No parameters found'}), 404
        
        # Get the JSON filename from session metadata
        json_filename = session_metadata.get('json_filename')
        if not json_filename:
            return jsonify({'error': 'No ProSiT JSON file associated with this session'}), 400
        
        # Get the path to the saved ProSiT JSON file
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        
        if not os.path.exists(json_filepath):
            return jsonify({'error': 'ProSiT parameter file not found'}), 404
        
        # Load the current ProSiT JSON (which includes any updates made through the UI)
        with open(json_filepath, 'r') as f:
            prosit_json = json.load(f)
        
        # Create temporary file with current parameters
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(prosit_json, f, indent=4)
            temp_path = f.name
        
        # Return the ProSiT simulator format JSON file
        return send_file(temp_path, as_attachment=True, 
                        download_name=f'prosit_parameters_{session_id}.json',
                        mimetype='application/json')
        
    except Exception as e:
        logger.error(f"Export parameters error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/get_activities_and_resources/<int:session_id>')
def get_activities_and_resources(session_id):
    """Get a list of all activities and resources from the simulated log."""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        sim_log_filename = session.simulation_df_filename

        if not sim_log_filename:
            return jsonify({'error': 'Simulated log file not found.'}), 404

        sim_log_filepath = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), sim_log_filename)
        if not os.path.exists(sim_log_filepath):
            return jsonify({'error': 'Simulated log file not found on server.'}), 404

        df = pd.read_csv(sim_log_filepath)
        
        activities = sorted(df['concept:name'].unique().tolist())
        resources = sorted(df['org:resource'].dropna().unique().tolist())

        return jsonify({'success': True, 'activities': activities, 'resources': resources})

    except Exception as e:
        logger.error(f"Get activities and resources error: {str(e)}")
        return jsonify({'error': f'Failed to get data: {str(e)}'}), 500


@app.route('/api/get_visualization/<int:session_id>/<visualization_type>')
def get_visualization(session_id, visualization_type):
    """Generate and return a specific visualization from the simulated log."""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        sim_log_filename = session.simulation_df_filename

        if not sim_log_filename:
            return jsonify({'error': 'Simulated log file not found.'}), 404

        sim_log_filepath = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), sim_log_filename)
        if not os.path.exists(sim_log_filepath):
            return jsonify({'error': 'Simulated log file not found on server.'}), 404

        df = pd.read_csv(sim_log_filepath)
        df["start:timestamp"] = pd.to_datetime(df["start:timestamp"], utc=True)
        df["time:timestamp"] = pd.to_datetime(df["time:timestamp"], utc=True)
        df["enabled:timestamp"] = pd.to_datetime(df["enabled:timestamp"], utc=True)

        plt.style.use('seaborn-v0_8-whitegrid')
        

        if visualization_type == 'process_map':
            log = pm4py.convert_to_event_log(df)
            # Use pm4py to convert dataframe to event log and then visualize
            performance_dfg, start_activities, end_activities = pm4py.discover_performance_dfg(log, case_id_key='case:concept:name', activity_key='concept:name', timestamp_key='time:timestamp')

            dfg_parameters = dfg_perf_visualizer.Parameters
            parameters = {}
            parameters[dfg_parameters.START_ACTIVITIES] = start_activities
            parameters[dfg_parameters.END_ACTIVITIES] = end_activities
            parameters[dfg_parameters.AGGREGATION_MEASURE] = "median"
            parameters["bgcolor"] = "white"
            gviz = dfg_perf_visualizer.apply(performance_dfg, parameters=parameters)
            # The pm4py view returns bytes, so we can directly encode it
            svg_content = gviz.pipe(format='svg', encoding='utf-8')

            logger.info(f"Process Map Plot Generated.")

            return jsonify({'success': True, 'visualization': svg_content})

            
        elif visualization_type == 'case_duration_dist':
            df['time:timestamp'] = pd.to_datetime(df['time:timestamp'], utc=True)
            df['start:timestamp'] = pd.to_datetime(df['start:timestamp'], utc=True)
            # Calculate durations per case
            case_starts = df.groupby('case:concept:name')['start:timestamp'].min()
            case_ends = df.groupby('case:concept:name')['time:timestamp'].max()
            case_durations = (case_ends - case_starts).dt.total_seconds() // 60

            metrics = {
                'average_case_duration': case_durations.mean(),
                'median_case_duration': case_durations.median(),
                'min_case_duration': case_durations.min(),
                'max_case_duration': case_durations.max()
            }

            # Plot density
            plt.figure(figsize=(10, 6))
            sns.histplot(case_durations, kde=True)
            plt.title('Case Duration Density Plot')
            plt.xlabel('Duration (minutes)')
            plt.ylabel('Frequency')

            # Save to SVG string
            svg_buffer = io.StringIO()
            plt.savefig(svg_buffer, format='svg')
            svg_buffer.seek(0)  # Important: rewind to start of the buffer
            svg_content = svg_buffer.getvalue()

            # Clean up
            plt.close()
            svg_buffer.close()

            logger.info(f"Case Duration Distribution Plot Generated.")

            return jsonify({'success': True, 'visualization': svg_content, 'metrics': metrics})

        elif visualization_type == 'resource_heatmap':
            resource_name = request.args.get('resource')

            # Filter resource only if a specific resource is selected
            if resource_name:
                df = df[df['org:resource'] == resource_name]

            # Parse timestamps
            df['time:timestamp'] = pd.to_datetime(df['time:timestamp'], utc=True)
            df['start:timestamp'] = pd.to_datetime(df['start:timestamp'], utc=True)

            # Extract hour and weekday
            df['hour'] = df['start:timestamp'].dt.hour
            df['weekday_num'] = df['start:timestamp'].dt.dayofweek
            weekday_map = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'}
            df['weekday'] = df['weekday_num'].map(weekday_map)

            # Count number of events per weekday-hour
            utilization = df.groupby(['weekday_num', 'hour']).size().unstack(fill_value=0)

            # Ensure full 7x24 grid
            utilization = utilization.reindex(index=np.arange(7), columns=np.arange(24), fill_value=0)

            # Create heatmap
            plt.figure(figsize=(14, 6))
            sns.heatmap(utilization, cmap="YlGnBu", annot=True, fmt="d", cbar_kws={'label': 'Number of events'})

            # Formatting
            title = f"Resource Event Count Heatmap: {resource_name}" if resource_name else "Resource Event Count Heatmap: All Resources"
            plt.title(title, fontsize=16)
            plt.xlabel("Hour of Day", fontsize=12)
            plt.ylabel("Weekday", fontsize=12)
            plt.yticks(ticks=np.arange(7)+0.5, labels=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'], rotation=0)

            plt.tight_layout()

            # Save to SVG string
            svg_buffer = io.StringIO()
            plt.savefig(svg_buffer, format='svg')
            svg_buffer.seek(0)  # Important: rewind to start of the buffer
            svg_content = svg_buffer.getvalue()

            # Clean up
            plt.close()
            svg_buffer.close()

            logger.info(f"Resource Heatmap Plot Generated.")

            return jsonify({'success': True, 'visualization': svg_content})


        elif visualization_type == 'activity_duration_boxplot':
            activity_name = request.args.get('activity')
            
            # Filter activity only if a specific activity is selected
            if activity_name:
                activity_df = df[df['concept:name'] == activity_name]
            else:
                activity_df = df
            activity_df['time:timestamp'] = pd.to_datetime(activity_df['time:timestamp'], utc=True)
            activity_df['start:timestamp'] = pd.to_datetime(activity_df['start:timestamp'], utc=True)
            activity_df['duration'] = (activity_df['time:timestamp'] - activity_df['start:timestamp']).dt.total_seconds() // 60
        
            metrics = {
                'average_duration': activity_df['duration'].mean(),
                'median_duration': activity_df['duration'].median(),
                'min_duration': activity_df['duration'].min(),
                'max_duration': activity_df['duration'].max()
            }
            
            plt.figure(figsize=(10, 6))
            sns.boxplot(y=activity_df['duration'], showfliers=False)
            title = f'Activity Duration for "{activity_name}"' if activity_name else 'Activity Duration for All Activities'
            plt.title(title)
            plt.ylabel('Duration (minutes)')

            # Save to SVG string
            svg_buffer = io.StringIO()
            plt.savefig(svg_buffer, format='svg')
            svg_buffer.seek(0)  # Important: rewind to start of the buffer
            svg_content = svg_buffer.getvalue()

            # Clean up
            plt.close()
            svg_buffer.close()

            logger.info(f"Activity Duration Plot Generated.")

            return jsonify({'success': True, 'visualization': svg_content, 'metrics': metrics})
        
        elif visualization_type == 'waiting_time_dist':
            activity_name = request.args.get('activity')
            resource_name = request.args.get('resource')

            activities = list(df['concept:name'].unique())
            resources = list(df['org:resource'].unique())

            # Apply filters only if specific values are provided
            if activity_name and activity_name in activities:
                if resource_name and resource_name in resources:
                    df = df[(df["org:resource"] == resource_name) & (df["concept:name"] == activity_name)]
                else:
                    df = df[(df["concept:name"] == activity_name)]
            else:
                if resource_name and resource_name in resources:
                    df = df[(df["org:resource"] == resource_name)]
                # If neither activity nor resource is specified, use all data

            df['enabled:timestamp'] = pd.to_datetime(df['enabled:timestamp'], utc=True)
            df['start:timestamp'] = pd.to_datetime(df['start:timestamp'], utc=True)
            df['waiting_time'] = (df['start:timestamp'] - df['enabled:timestamp']).dt.total_seconds() // 60
            
            metrics = {
                'average_duration': df['waiting_time'].mean(),
                'median_duration': df['waiting_time'].median(),
                'min_duration': df['waiting_time'].min(),
                'max_duration': df['waiting_time'].max()
            }

            # Plot density
            plt.figure(figsize=(10, 6))
            sns.histplot(df['waiting_time'], kde=True)
            
            # Create title based on selected filters
            title_parts = []
            if resource_name and resource_name in resources:
                title_parts.append(f'Resource: {resource_name}')
            elif not resource_name:
                title_parts.append('Resource: Any')
                
            if activity_name and activity_name in activities:
                title_parts.append(f'Activity: {activity_name}')
            elif not activity_name:
                title_parts.append('Activity: Any')
                
            plt.title(' -- '.join(title_parts) if title_parts else 'Waiting Time Distribution')
            plt.xlabel('Duration (minutes)')
            plt.ylabel('Frequency')

            # Save to SVG string
            svg_buffer = io.StringIO()
            plt.savefig(svg_buffer, format='svg')
            svg_buffer.seek(0)  # Important: rewind to start of the buffer
            svg_content = svg_buffer.getvalue()

            # Clean up
            plt.close()
            svg_buffer.close()

            logger.info(f"Waiting Time Distribution Plot Generated.")

            return jsonify({'success': True, 'visualization': svg_content, 'metrics': metrics})

        else:
            return jsonify({'error': 'Invalid visualization type.'}), 400

    except Exception as e:
        logger.error(f"Visualization error for {visualization_type}: {str(e)}")
        return jsonify({'error': f'Failed to generate visualization: {str(e)}'}), 500

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500