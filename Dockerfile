FROM python:3.14-slim as base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes gosu \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./

# Test stage: includes dev dependencies and Playwright/Chromium
FROM base as test

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
      libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
      libcups2 libxkbcommon0 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

RUN poetry install --no-root

COPY README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY tests ./tests

RUN poetry install \
    && poetry run playwright install --with-deps chromium

# Production stage
FROM base as production

ENV TRAECT_HOST=0.0.0.0 \
    TRAECT_PORT=8000 \
    TRAECT_DATABASE_URL=sqlite:////data/traect.db

RUN poetry install --only main --no-root

COPY README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations

RUN poetry install --only main \
    && useradd --create-home --uid 10001 traect \
    && mkdir /data \
    && chown traect:traect /data

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN chmod 755 /usr/local/bin/docker-entrypoint

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint"]
CMD ["traect"]
