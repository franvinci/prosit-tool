"""``python -m prosit_tool`` — same as the ``prosit-tool`` command."""

import sys

from .cli import main

if __name__ == '__main__':
    sys.exit(main())
