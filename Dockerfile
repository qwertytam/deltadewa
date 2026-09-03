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
# #325: the /design import picker's second listed source
# (examples/portfolios/, see deltadewa/state.py's _DEFAULT_EXAMPLES_DIR) —
# without this the picker's server-side list is silently empty in
# production, even though it works in a dev checkout.
COPY examples ./examples
COPY README.md ./
RUN poetry install --only main


FROM python:3.11-slim AS runtime

# UID/GID the app actually runs as (docker-entrypoint.sh), fixed rather
# than left to whatever order packages happen to install in. Default 1000
# matches the first non-root user `adduser` creates on a fresh Ubuntu
# droplet (docs/RUNBOOK.md §1's `deploy` user) — override at build time
# via compose.yaml's build.args (APP_UID/APP_GID, sourced from .env) if a
# given droplet's `deploy` UID differs; check with `id deploy`. See #220.
ARG APP_UID=1000
ARG APP_GID=1000
# -m (not -M): gunicorn >=25.1 defaults its control socket to
# $HOME/.gunicorn/ (gunicorn/config.py's ControlSocket setting) and creates
# that directory itself at startup — a homeless user makes every start log
# a "Permission denied: '/home/appuser'" control-server error (harmless to
# request handling, but noisy on every boot). A real, appuser-owned home
# lets gunicorn create it normally.
RUN groupadd -g "${APP_GID}" appuser \
    && useradd -u "${APP_UID}" -g "${APP_GID}" -m -s /usr/sbin/nologin appuser

WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    DELTADEWA_HOST=0.0.0.0 \
    DELTADEWA_PORT=8050

COPY --from=builder /app /app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8050

# No USER directive: the image's default (root) is required so
# docker-entrypoint.sh can chown the exports/ bind mount on every start
# before dropping to appuser — see that script and issue #220.
ENTRYPOINT ["docker-entrypoint.sh"]

# --workers 1: ProgramState (deltadewa/state.py) is one shared in-memory
# instance per process — a second worker process would fork it into a
# second, independently-drifting portfolio. Concurrency instead comes from
# --worker-class gthread --threads: threads share the one process's memory,
# so ProgramState stays a single instance.
CMD gunicorn --bind ${DELTADEWA_HOST}:${DELTADEWA_PORT} \
    --workers 1 --worker-class gthread --threads 4 \
    "deltadewa.app.wsgi:server()"
