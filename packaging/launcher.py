"""What the executable built by PyInstaller runs (see prosit-tool.spec)."""

import sys

from prosit_tool.cli import main

if __name__ == '__main__':
    sys.exit(main())
