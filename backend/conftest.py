"""Top-level pytest conftest.

Sole purpose: prepend ``backend/`` to ``sys.path`` before pytest imports any
lower conftest. uv treats this project as a virtual workspace
(``source = virtual = "."`` in uv.lock), so the ``evals`` package never
lands in site-packages. The eval suite's conftest does an absolute
``from evals.lib.judge import ...``, which would otherwise raise
``ModuleNotFoundError`` under a fresh CI venv.

The ``[tool.pytest.ini_options].pythonpath`` knob also helps locally, but
loads later than conftest discovery on some pytest/uv combos — keeping a
top-level conftest makes the import deterministic across environments.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
