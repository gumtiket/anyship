"""Join main's deployment schema and the existing AI branch history."""

revision = "0010_merge_ai_deployments"
down_revision = ("0008", "0009")
branch_labels = None
depends_on = None


def upgrade():
    # Alembic first applies whichever parent is missing. No existing data changes.
    pass


def downgrade():
    pass
