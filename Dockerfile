# RedHood Systems pipeline image.
#
# Secrets (ANTHROPIC_API_KEY, GITHUB_TOKEN) are NOT baked in — pass them at
# runtime with `--env-file .env` or `-e`. State (redhood.db, data/) is meant to
# be bind-mounted so runs persist across containers; see docker-compose.yml.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Run as a non-root user. UID/GID default to 1000 (the usual first host user)
# so bind-mounted redhood.db and data/ stay writable; override with
# `--build-arg UID=$(id -u) --build-arg GID=$(id -g)` (or HOST_UID/HOST_GID with
# docker compose) if yours differ.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid "${GID}" redhood \
 && useradd --uid "${UID}" --gid "${GID}" --create-home --shell /usr/sbin/nologin redhood

WORKDIR /app

# Dependencies first so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=redhood:redhood . .

# /app must be writable by the app user: SQLite creates its journal file next
# to redhood.db, and the aggregator creates data/ on first run.
RUN mkdir -p data && chown redhood:redhood /app /app/data

USER redhood

ENTRYPOINT ["python", "redhood_aggregator.py"]
CMD ["--hours", "1"]
