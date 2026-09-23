"""Adds `backend/scripts` to `sys.path`.

`pyproject.toml`'s `pythonpath` only covers `src`, so a script module (e.g.
`check_venue_fill_windows`) is otherwise unimportable from a test -- the same
reason the script itself bootstraps `probe_credentials` at runtime instead of
relying on an ambient path.
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
