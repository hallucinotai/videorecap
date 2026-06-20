"""Add intermediate_keys field to track step-by-step outputs

Revision ID: 008
Revises: 007
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recap_jobs", sa.Column("intermediate_keys", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("recap_jobs", "intermediate_keys")
