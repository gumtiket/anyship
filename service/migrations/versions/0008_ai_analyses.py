"""Development fake AI analysis history and reviewed bundles."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("active_project_id", sa.String(36), nullable=True, unique=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("base_tree", sa.String(40), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("logs_json", sa.Text(), nullable=False),
        sa.Column("review_hash", sa.String(64), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", sa.BigInteger(), nullable=True),
        sa.Column("lease_until", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("project_id", "request_id", name="uq_ai_analysis_request"))
    op.create_index("ix_ai_analyses_project_id", "ai_analyses", ["project_id"])


def downgrade():
    op.drop_table("ai_analyses")
