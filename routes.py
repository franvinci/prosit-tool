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
    """Handle XES file upload"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        noise_threshold = float(request.form.get('noise_threshold', 0.2))
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Only XES and PNML files are supported'}), 400
        
        # Save file
        if file.filename is None:
            return jsonify({'error': 'Invalid filename'}), 400
            
        filename = secure_filename(file.filename)
        timestamp = int(datetime.now().timestamp())
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Create session
        session = SimulationSession(
            filename=filename,
            noise_threshold=noise_threshold
        )
        db.session.add(session)
        db.session.commit()
        
        logger.info(f"File uploaded successfully: {filename}")
        return jsonify({
            'success': True,
            'session_id': session.id,
            'filename': filename,
            'message': 'File uploaded successfully'
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
        
        # Process file based on type
        if is_pnml:
            logger.info(f"Importing PNML model for session {session_id}")
            parameters = prosit.import_pnml_model(filepath)
            process_model = parameters.get('process_model', {})
        else:
            logger.info(f"Discovering process model for session {session_id}")
            process_model = prosit.discover_process_model(filepath, session.noise_threshold)
            
            # Discover parameters
            logger.info(f"Discovering parameters for session {session_id}")
            parameters = prosit.discover_parameters(filepath, process_model)
        
        # Save parameters
        session.set_parameters(parameters)
        session.status = 'ready'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'parameters': parameters,
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
        parameters = session.get_parameters()
        
        if not parameters:
            return jsonify({'error': 'No parameters found'}), 404
        
        return jsonify({
            'success': True,
            'parameters': parameters,
            'status': session.status
        })
        
    except Exception as e:
        logger.error(f"Get parameters error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/parameters/<int:session_id>', methods=['PUT'])
def update_parameters(session_id):
    """Update parameters for a session"""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        
        new_parameters = request.get_json()
        if not new_parameters:
            return jsonify({'error': 'No parameters provided'}), 400
        
        # Validate parameters structure
        required_sections = ['transition_params', 'resource_params', 'execution_time_params', 'waiting_time_params']
        for section in required_sections:
            if section not in new_parameters:
                return jsonify({'error': f'Missing required section: {section}'}), 400
        
        # Update parameters
        session.set_parameters(new_parameters)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Parameters updated successfully'
        })
        
    except Exception as e:
        logger.error(f"Update parameters error: {str(e)}")
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
    """Export parameters as JSON file"""
    try:
        session = SimulationSession.query.get_or_404(session_id)
        parameters = session.get_parameters()
        
        if not parameters:
            return jsonify({'error': 'No parameters found'}), 404
        
        # Create temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(parameters, f, indent=2)
            temp_path = f.name
        
        return send_file(temp_path, as_attachment=True, 
                        download_name=f'parameters_{session_id}.json',
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
