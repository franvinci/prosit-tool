from app import db
from datetime import datetime
import json

from config import Config


class SimulationSession(db.Model):
    """Database model for simulation sessions."""

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    noise_threshold = db.Column(db.Float, default=Config.DEFAULT_NOISE_THRESHOLD)
    parameters = db.Column(db.Text)  # JSON string of discovered parameters
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='uploaded')  # uploaded, discovering, ready, simulating, completed, error
    simulation_df_filename = db.Column(db.String(255), default='')

    def __init__(self, filename, noise_threshold=Config.DEFAULT_NOISE_THRESHOLD, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.noise_threshold = noise_threshold
        self.status = 'uploaded'
    
    def get_parameters(self):
        """Get parameters as Python dictionary.
        
        Returns:
            dict or None: Parsed JSON parameters or None if empty
        """
        if self.parameters:
            return json.loads(self.parameters)
        return None
    
    def set_parameters(self, params_dict):
        """Set parameters from Python dictionary.
        
        Args:
            params_dict: Dictionary to store as JSON string
        """
        self.parameters = json.dumps(params_dict, indent=2)
