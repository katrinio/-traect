# Storage

The project stores its data in a SQL database through SQLAlchemy.

## What is stored

- workspaces
- domains
- weeks
- per-week domain states

## Where it lives

The database location is configured outside the codebase.
For local development, Alembic defaults to `sqlite:///traect.db` unless `TRAECT_DATABASE_URL` is set.

## Behavior

- application writes go through the ORM
- schema changes are applied with Alembic migrations
- domain data is not embedded in UI code

## Notes

The model is intentionally small so it can support future workspace types without a rewrite.
