# Canonical AI Job Assistant -- FastAPI application.
#
# This image serves the API in src/api/. It contains no browser, no Chrome, and
# no Selenium: the canonical application performs no browser automation, and
# real application submission is disabled (see src/safety/).
#
# The previous image in this repository installed Chrome plus ~35 X11/GTK
# libraries, copied only the root-level legacy scripts, and ran
# `python3 linkedin.py` -- the quarantined auto-applier. That path is
# intentionally not reproduced here.

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The canonical packages live directly under src/ and use absolute imports
# (`from core.settings import ...`), so src/ must precede the standard library
# on sys.path. This is the same arrangement job_assistant.py and
# tests/conftest.py use. It is required, not cosmetic: one package is named
# `profile`, which collides with the stdlib `profile` module on Python <= 3.11.
ENV PYTHONPATH=/app/src

# Copy the package sources alongside the metadata. Both are required before
# `pip install .`: setuptools resolves the wheel's contents from src/, so
# installing with only pyproject.toml present fails at "getting requirements to
# build wheel". Source edits therefore invalidate this layer.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# The CLI shim, so `python job_assistant.py ...` also works in the container.
# Only this file: the root-level legacy bot scripts (linkedin.py, config.py,
# utils.py, constants.py) are deliberately not copied into the image.
COPY job_assistant.py ./

# Local data directory: SQLite database, profile JSON, parsed resume text.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Safety defaults, stated explicitly so the container is safe even if no .env
# is mounted. These match src/core/settings.py; a permissive value here makes
# the process refuse to start (assert_phase2_invariants).
ENV ASSISTANT_SAFETY__SAFE_MODE=true \
    ASSISTANT_SAFETY__DRY_RUN=true \
    ASSISTANT_SAFETY__REQUIRE_HUMAN_APPROVAL=true \
    ASSISTANT_SAFETY__ALLOW_FINAL_SUBMISSION=false \
    ASSISTANT_SAFETY__ALLOW_FORM_FILLING=false \
    ASSISTANT_SAFETY__ALLOW_BROWSER_NAVIGATION=false \
    ASSISTANT_SAFETY__ALLOW_FILE_UPLOAD=false \
    ASSISTANT_DATABASE__PATH=/app/data/assistant.db

EXPOSE 8000

# Readiness, not liveness: this checks SQLite, migrations, and the safety
# invariants, so a container that cannot serve is reported unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status==200 else 1)"]

CMD ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]