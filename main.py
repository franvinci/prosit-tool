"""Run ProSiT from a source checkout.

Unlike the installed ``prosit-tool`` command, which keeps its files in the
per-user data directory, this keeps them inside the checkout (``uploads/``,
``simulations/``, ``instance/``), where a checkout has always kept them.
Any option of ``prosit-tool`` can be appended, e.g. ``python main.py --no-browser``.
"""

import sys
from pathlib import Path

from prosit_tool.cli import main

if __name__ == '__main__':
    checkout = Path(__file__).resolve().parent
    sys.exit(main(['--data-dir', str(checkout), *sys.argv[1:]]))
