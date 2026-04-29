"""Main entry point for the ProSiT application."""

from app import app
from config import Config

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=Config.PORT)
