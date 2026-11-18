"""Flask extensions, created unbound so that any module can import them.

They are attached to an application in :func:`prosit_tool.app.create_app`.
"""

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
