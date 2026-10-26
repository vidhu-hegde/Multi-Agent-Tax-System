# SilverFile: one image for taxpayer sessions, staff commands and the tests.
# The API key is never baked in: docker compose passes .env at run time (see README > Docker).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SILVERFILE_DB_PATH=/data/silverfile.sqlite

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Non-root user. Sessions live on the /data volume, so they survive restarts and can be shared
# with the dashboard container.
RUN useradd --create-home --uid 1000 silverfile \
    && mkdir -p /data /app/output \
    && chown -R silverfile /data /app/output
USER silverfile
VOLUME ["/data"]

ENTRYPOINT ["python", "run.py"]
CMD ["--help"]
