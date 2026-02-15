"""remove mobile fields and guest_otps table

Revision ID: 0002_remove_mobile_fields
Revises: 0001_add_guest_schema
Create Date: 2026-02-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002_remove_mobile_fields'
down_revision = '0001_add_guest_schema'
branch_labels = None
depends_on = None


def upgrade():
    # Drop guest_otps table if it exists
    try:
        op.execute('DROP TABLE IF EXISTS guest_otps;')
    except Exception:
        pass

    # Remove mobile_number columns from various tables if present
    tables = ['users', 'events', 'teams', 'team_invitations', 'certificate_templates']
    for t in tables:
        try:
            # MySQL syntax: check if column exists before dropping (safe on most DBs)
            op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS mobile_number;")
        except Exception:
            # Fallback for DBs that do not support IF EXISTS in ALTER
            try:
                op.execute(f"ALTER TABLE {t} DROP COLUMN mobile_number;")
            except Exception:
                # ignore if column not present
                pass

    # Drop index if present
    try:
        op.execute("DROP INDEX IF EXISTS idx_users_mobile ON users;")
    except Exception:
        try:
            op.execute("DROP INDEX idx_users_mobile;")
        except Exception:
            pass


def downgrade():
    # Downgrade is intentionally a no-op to avoid destructive recreation of columns
    print('Downgrade skipped to avoid recreating dropped mobile columns.')
