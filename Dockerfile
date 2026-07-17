FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH=/app/src \
    TRAECT_HOST=0.0.0.0 \
    TRAECT_PORT=8000 \
    TRAECT_DATABASE_URL=sqlite:////app/data/traect.db

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes gosu \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

COPY README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations

RUN poetry install --only main \
    && useradd --create-home --uid 10001 traect \
    && mkdir /app/data \
    && chown traect:traect /app/data

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN chmod 755 /usr/local/bin/docker-entrypoint

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint"]
CMD ["traect"]
