"""Pinned source branches and recoverable work-branch publication."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    for name, length, default in (("base_branch", 255, ""), ("provider", 16, "fake"),
            ("work_branch", 255, ""), ("commit_sha", 40, ""), ("publish_token", 36, "")):
        op.add_column("ai_analyses", sa.Column(name, sa.String(length), nullable=False, server_default=default))
    op.add_column("ai_analyses", sa.Column("branch_created", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    for name in ("branch_created", "publish_token", "commit_sha", "work_branch", "provider", "base_branch"):
        op.drop_column("ai_analyses", name)
