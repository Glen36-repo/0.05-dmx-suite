"""Entry point for the packaged app (dmx-suite.exe)."""

import sys

from dmx_suite.cli import main

if __name__ == "__main__":
    sys.exit(main())
