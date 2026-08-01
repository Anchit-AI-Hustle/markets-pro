"""Test package.

Inserts ``src/`` on the path so the suite runs against the working tree with no
install step. ``python -m unittest discover -s tests -t .`` from the repo root
is all that is required.
"""

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
