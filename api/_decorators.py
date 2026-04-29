"""Shared decorators for the prosit-tool API blueprints."""

import logging
import uuid
from functools import wraps

from flask import jsonify

logger = logging.getLogger(__name__)


def handle_api_errors(default_message: str, status_code: int = 500):
    """Catch unhandled exceptions in a view and return a generic JSON 500.

    Logs the full traceback server-side via ``logger.exception`` and returns a
    body that does not leak internals (paths, SQL, stack frames). Each error
    gets a UUID ``error_id`` echoed in both log and response so an operator can
    correlate a user-facing failure to its server log entry.

    Use directly above the route's view function (after ``@bp.route(...)``):

        @bp.route('/api/foo')
        @handle_api_errors('Failed to do foo')
        def foo():
            ...
    """
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            try:
                return view(*args, **kwargs)
            except Exception:
                error_id = uuid.uuid4().hex
                logger.exception("%s [error_id=%s]", default_message, error_id)
                return jsonify({'error': default_message, 'error_id': error_id}), status_code
        return wrapper
    return decorator
