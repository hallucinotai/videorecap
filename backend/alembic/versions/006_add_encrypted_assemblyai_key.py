"""Add encrypted_assemblyai_key column to users table

Revision ID: 006
Revises: 005
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("encrypted_assemblyai_key", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "encrypted_assemblyai_key")
