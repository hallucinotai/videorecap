"""Add emotion analysis status and error tracking

Revision ID: 005
Revises: 004
Create Date: 2026-05-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recap_jobs', sa.Column('emotion_analysis_status', sa.String(), nullable=True))
    op.add_column('recap_jobs', sa.Column('emotion_analysis_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('recap_jobs', 'emotion_analysis_error')
    op.drop_column('recap_jobs', 'emotion_analysis_status')
