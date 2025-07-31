import os
import json
import logging
from datetime import datetime
from flask import render_template, request, jsonify, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename
from app import app, db
from models import SimulationSession
from prosit_integration import ProSiTIntegration

logger = logging.getLogger(__name__)
prosit = ProSiTIntegration()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['xes', 'pnml']

@app.route('/')
def index():
    """Main page"""
    sessions = SimulationSession.query.order_by(SimulationSession.created_at.desc()).limit(10).all()
    return render_template('index.html', sessions=sessions)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle XES file upload with optional PNML file"""
    try:
        if 'xes_file' not in request.files:
            return jsonify({'error': 'No XES file provided'}), 400
        
        xes_file = request.files['xes_file']
        pnml_file = request.files.get('pnml_file')
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
            # For now, store in parameters as we don't have pnml_filename field
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
        
        # Determine file type
        is_pnml = session.filename.lower().endswith('.pnml')
        is_xes = session.filename.lower().endswith('.xes')
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        # Update status
        session.status = 'discovering'
        db.session.commit()
        
        # Always discover parameters from XES file
        logger.info(f"Discovering parameters from XES file for session {session_id}")
        
        # Check if there's a separate PNML file for the Petri net model
        pnml_filepath = None
        session_params = session.get_parameters()
        if session_params and 'pnml_filename' in session_params:
            pnml_filepath = os.path.join(app.config['UPLOAD_FOLDER'], session_params['pnml_filename'])
        
        if pnml_filepath and os.path.exists(pnml_filepath):
            # Use imported PNML model but discover parameters from XES
            logger.info(f"Using PNML model and discovering parameters from XES")
            process_model = prosit.import_petri_net_from_pnml(pnml_filepath)
            parameters = prosit.discover_parameters(filepath, process_model)
        else:
            # Standard workflow: discover both model and parameters from XES
            logger.info(f"Discovering process model and parameters from XES")
            process_model = prosit.discover_process_model(filepath, session.noise_threshold)
            parameters = prosit.discover_parameters(filepath, process_model)
        
        # Save parameters to JSON file
        timestamp = int(datetime.now().timestamp())
        json_filename = f"{timestamp}_parameters.json"
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        prosit.save_parameters_to_json(json_filepath)
        
        # Load parameters back from JSON to get the correct format
        logger.info(f"Loading parameters from saved JSON file: {json_filename}")
        parameters = prosit.load_parameters_from_json_file(json_filepath)
        
        # Store metadata in session
        session.set_parameters({
            'json_filename': json_filename,
            'process_model': {
                'visualization': process_model.get('visualization') or process_model.get('svg_content'),
                'activities': process_model.get('activities', []),
                'transitions': process_model.get('transitions', []),
                'places': process_model.get('places', [])
            }
        })
        session.status = 'ready'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'parameters': parameters,
            'json_filename': json_filename,
            'process_model': {
                'visualization': process_model.get('visualization') or process_model.get('svg_content'),
                'activities': process_model.get('activities', []),
                'transitions': process_model.get('transitions', []),
                'places': process_model.get('places', [])
            },
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
    """Convert application parameters back to ProSiT JSON format"""
    try:
        # Update transition weights
        if 'transition_params' in app_params and 'transition_weights' in app_params['transition_params']:
            prosit_json['transition_params']['transition_weights'] = app_params['transition_params']['transition_weights']
        
        # Update execution time parameters
        if 'execution_time_params' in app_params and 'activity_durations' in app_params['execution_time_params']:
            for activity, params in app_params['execution_time_params']['activity_durations'].items():
                dist = params.get('distribution', 'norm')
                param_values = params.get('parameters', {})
                
                prosit_entry = {
                    'dist_name': dist,
                    'min_value': param_values.get('min_value', 0.0),
                    'max_value': param_values.get('max_value', 100.0),
                    'mean_value': param_values.get('mean_value', 10.0)
                }
                
                # Convert parameters based on distribution type
                if dist == 'fixed':
                    prosit_entry['params'] = [param_values.get('value', 10.0)]
                elif dist == 'norm':
                    prosit_entry['params'] = [
                        param_values.get('mean', 10.0),
                        param_values.get('std', 2.0)
                    ]
                elif dist == 'expon':
                    prosit_entry['params'] = [
                        0.0,
                        param_values.get('scale', 10.0)
                    ]
                elif dist == 'lognorm':
                    prosit_entry['params'] = [
                        param_values.get('s', 1.0),
                        param_values.get('loc', 0.0),
                        param_values.get('scale', 1.0)
                    ]
                
                prosit_json['execution_time_params']['execution_time_distributions'][activity] = prosit_entry
        
        # Update waiting time parameters
        if 'waiting_time_params' in app_params and 'waiting_time' in app_params['waiting_time_params']:
            for resource, params in app_params['waiting_time_params']['waiting_time'].items():
                dist = params.get('distribution', 'expon')
                param_values = params.get('parameters', {})
                
                prosit_entry = {
                    'dist_name': dist,
                    'min_value': param_values.get('min_value', 0.0),
                    'max_value': param_values.get('max_value', 1000.0),
                    'mean_value': param_values.get('mean_value', 120.0)
                }
                
                # Convert parameters based on distribution type
                if dist == 'fixed':
                    prosit_entry['params'] = [param_values.get('value', 120.0)]
                elif dist == 'norm':
                    prosit_entry['params'] = [
                        param_values.get('mean', 120.0),
                        param_values.get('std', 30.0)
                    ]
                elif dist == 'expon':
                    prosit_entry['params'] = [
                        0.0,
                        param_values.get('scale', 120.0)
                    ]
                elif dist == 'lognorm':
                    prosit_entry['params'] = [
                        param_values.get('s', 1.0),
                        param_values.get('loc', 0.0),
                        param_values.get('scale', 120.0)
                    ]
                
                prosit_json['waiting_time_params']['waiting_time_distributions'][resource] = prosit_entry
        
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
                        'dist_name': 'expon',
                        'params': [0.0, 120.0],  # scale = 120 minutes
                        'min_value': 0.0,
                        'max_value': 1000.0,
                        'mean_value': 120.0
                    }
        
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
            from datetime import datetime
            start_timestamp = datetime.fromisoformat(start_timestamp_str.replace('Z', '+00:00'))
        else:
            start_timestamp = None
        
        # Load process model and run simulation using ProSiT
        logger.info(f"Starting simulation for session {session_id} with {num_instances} instances")
        
        # Get original file path to reload process model
        original_filename = session.filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
        
        # Reload process model
        process_model = prosit.discover_process_model(filepath, session.noise_threshold)
        
        # Discover parameters from the event log to get ProSiT params object
        prosit.discover_parameters(filepath, process_model)
        
        # Run simulation using ProSiT
        result_df = prosit.run_simulation(n_traces=num_instances, start_timestamp=start_timestamp)
        
        # Save simulation results as XES file
        output_filename = f'simulation_{session_id}_{num_instances}traces.csv'
        output_path = os.path.join(app.config.get('SIMULATION_FOLDER', 'simulations'), output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result_df.to_csv(output_path, index=False)
        
        # Update status
        session.status = 'completed'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'output_path': output_filename,
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
        filepath = os.path.join(app.config['SIMULATION_FOLDER'], filename)
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
        import tempfile
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

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500
