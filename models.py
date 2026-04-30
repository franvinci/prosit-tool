from app import db
from datetime import datetime
import json

from config import Config


BASELINE_RUN_NAME = 'As-Is'


class SimulationSession(db.Model):
    """One uploaded event log + discovered baseline parameters.

    A session owns one or more ``SimulationRun`` records ("what-if" scenarios).
    The baseline ("As-Is") run captures the parameters as discovered from the
    log; user-created what-ifs branch off from there.
    """

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(255))
    noise_threshold = db.Column(db.Float, default=Config.DEFAULT_NOISE_THRESHOLD)
    parameters = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='uploaded')

    runs = db.relationship(
        'SimulationRun', backref='session',
        cascade='all, delete-orphan', order_by='SimulationRun.created_at',
    )

    def __init__(self, filename, noise_threshold=Config.DEFAULT_NOISE_THRESHOLD, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.noise_threshold = noise_threshold
        self.status = 'uploaded'
        self.last_used_at = datetime.utcnow()

    def get_parameters(self):
        if self.parameters:
            return json.loads(self.parameters)
        return None

    def set_parameters(self, params_dict):
        self.parameters = json.dumps(params_dict, indent=2)

    def touch(self):
        self.last_used_at = datetime.utcnow()

    def get_baseline_run(self):
        for run in self.runs:
            if run.is_baseline:
                return run
        return None

    def display_label(self):
        """Human-friendly label: explicit display_name, else filename minus the
        ``<timestamp>_`` prefix and trailing ``.xes``."""
        if self.display_name:
            return self.display_name
        name = self.filename or ''
        # Strip the leading "<unix-timestamp>_" we add at upload time.
        first_underscore = name.find('_')
        if first_underscore > 0 and name[:first_underscore].isdigit():
            name = name[first_underscore + 1:]
        if name.lower().endswith('.xes'):
            name = name[:-4]
        return name or self.filename


class SimulationRun(db.Model):
    """A single what-if analysis: a named parameter set and its simulation log.

    The baseline run (``is_baseline=True``, name == ``BASELINE_RUN_NAME``) is
    immutable and represents the discovered parameters as-is. User-created
    runs can be edited freely.
    """

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey('simulation_session.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    name = db.Column(db.String(255), nullable=False, default=BASELINE_RUN_NAME)
    parameters_filename = db.Column(db.String(255))
    simulation_df_filename = db.Column(db.String(255))
    num_instances = db.Column(db.Integer)
    is_baseline = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_run_at = db.Column(db.DateTime)

    def to_summary(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'name': self.name,
            'is_baseline': bool(self.is_baseline),
            'num_instances': self.num_instances,
            'has_simulation': bool(self.simulation_df_filename),
            'simulation_df_filename': self.simulation_df_filename or None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
        }
