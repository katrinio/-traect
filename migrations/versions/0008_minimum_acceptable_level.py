"""Squashed baseline for the current Traect schema.

Revision ID: 0008_minimum_acceptable_level
Revises: None

The revision identifier is intentionally retained so databases already upgraded
to the former migration chain remain at the current Alembic head.
"""

from __future__ import annotations

from alembic import op

from traect.db.base import Base
from traect.domain import models as _models  # noqa: F401

revision = "0008_minimum_acceptable_level"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
