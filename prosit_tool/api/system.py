"""Endpoints about the running application itself."""

from flask import Blueprint, jsonify

from .. import __version__
from ..config import APP_NAME

bp = Blueprint('system', __name__)


@bp.route('/api/health')
def health():
    """Identify this server.

    The launcher calls it before starting: if the port is already answered by
    another ProSiT, it opens that one instead of failing with "port in use".
    """
    return jsonify({'app': APP_NAME, 'version': __version__, 'status': 'ok'})
