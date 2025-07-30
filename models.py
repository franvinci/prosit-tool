from app import db
from datetime import datetime
import json

class SimulationSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    noise_threshold = db.Column(db.Float, default=0.2)
    parameters = db.Column(db.Text)  # JSON string of discovered parameters
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='uploaded')  # uploaded, discovered, ready, simulating, completed
    
    def __init__(self, filename, noise_threshold=0.2, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename 
        self.noise_threshold = noise_threshold
        self.status = 'uploaded'
    
    def get_parameters(self):
        """Get parameters as Python dict"""
        if self.parameters:
            return json.loads(self.parameters)
        return None
    
    def set_parameters(self, params_dict):
        """Set parameters from Python dict"""
        self.parameters = json.dumps(params_dict, indent=2)
