#!/usr/bin/env python
"""AI Job Assistant - command line entry point.

    python job_assistant.py status
    python job_assistant.py profile init
    python job_assistant.py profile unknown
    python job_assistant.py resume ingest C:/resumes/cv.pdf --variant "AI Engineer"
    python job_assistant.py acceptance

Why the script is named ``job_assistant.py`` and not ``assistant.py``: the CLI
lives in the ``src/assistant/`` package. A root file named ``assistant.py``
would shadow that package whenever the project root precedes ``src`` on
``sys.path``, which is the default for ``python -c`` and for several test
runners. Naming them differently removes the collision entirely.

The legacy bot is untouched and is not invoked by any command here.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# ``src`` must come first so ``import assistant`` resolves to the CLI package.
# ROOT stays available because the legacy root modules (config, utils,
# constants) live there and must keep importing under their original names.
for candidate in (str(ROOT), str(SRC)):
    if candidate in sys.path:
        sys.path.remove(candidate)
    sys.path.insert(0, candidate)

if sys.path.index(str(SRC)) > sys.path.index(str(ROOT)):  # pragma: no cover
    raise RuntimeError(
        "src must precede the project root on sys.path, otherwise the CLI "
        "package cannot be imported"
    )

if __name__ == "__main__":
    from assistant.cli import main

    raise SystemExit(main(sys.argv[1:]))
