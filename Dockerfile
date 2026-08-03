# syntax=docker/dockerfile:1

# Matches CI's python-version: "3.11" (.github/workflows/ci.yml) at the
# same floating-minor granularity actions/setup-python uses.
FROM python:3.11-slim AS builder

ENV POETRY_VERSION=2.4.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# Dependency layer cached separately from app code so an app-only change
# doesn't invalidate the (slow) dependency install.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

COPY deltadewa ./deltadewa
COPY config ./config
COPY README.md ./
RUN poetry install --only main


FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    DELTADEWA_HOST=0.0.0.0 \
    DELTADEWA_PORT=8050

COPY --from=builder /app /app

EXPOSE 8050

# --workers 1: ProgramState (deltadewa/state.py) is one shared in-memory
# instance per process — a second worker process would fork it into a
# second, independently-drifting portfolio. Concurrency instead comes from
# --worker-class gthread --threads: threads share the one process's memory,
# so ProgramState stays a single instance.
CMD gunicorn --bind ${DELTADEWA_HOST}:${DELTADEWA_PORT} \
    --workers 1 --worker-class gthread --threads 4 \
    "deltadewa.app.wsgi:server()"
