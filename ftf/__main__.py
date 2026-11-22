"""`python -m ftf <command>` is the same as `python -m ftf.cli <command>`."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
