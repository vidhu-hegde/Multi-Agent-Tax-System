# SilverFile: one image for the tax_math MCP server, the staff dashboard and run.py (see docker-compose.yml).
# No .env or keys are baked in (.dockerignore); compose passes them at run time from .env.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SILVERFILE_DB_PATH=/app/state/silverfile.sqlite

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# The code stays owned by root, so the app cannot rewrite it. Only the SQLite state and generated output
# (demo database, demo case files, HTML drafts) are writable; compose mounts named volumes on both.
COPY . .
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin silverfile \
    && mkdir -p /app/state /app/output \
    && chown silverfile:silverfile /app/state /app/output
USER silverfile

CMD ["python", "run.py", "--help"]
