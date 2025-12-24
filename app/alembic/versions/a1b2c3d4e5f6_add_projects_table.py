"""Add projects table

Revision ID: a1b2c3d4e5f6
Revises: 1a31ce608336
Create Date: 2025-12-23 17:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '1a31ce608336'
branch_labels = None
depends_on = None


def upgrade():
    # Create projects table
    op.create_table(
        'projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('seed_url', sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
        sa.Column('settings', sa.JSON(), nullable=False),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_audit_at', sa.DateTime(), nullable=True),
        sa.Column('last_gsc_sync_at', sa.DateTime(), nullable=True),
        sa.Column('last_serp_refresh_at', sa.DateTime(), nullable=True),
        sa.Column('last_links_snapshot_at', sa.DateTime(), nullable=True),
        sa.Column('last_ppc_sync_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    # Create index on name column
    op.create_index(op.f('ix_projects_name'), 'projects', ['name'], unique=False)


def downgrade():
    # Drop index
    op.drop_index(op.f('ix_projects_name'), table_name='projects')
    # Drop table
    op.drop_table('projects')
