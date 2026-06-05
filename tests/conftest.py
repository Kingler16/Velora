"""Test-Bootstrap: Repo-Root in sys.path, damit `import src.…` funktioniert.

Redundant zu `pythonpath = .` in pytest.ini, aber robust gegen ältere
pytest-Versionen und gegen Aufrufe von ausserhalb des Repo-Roots.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
