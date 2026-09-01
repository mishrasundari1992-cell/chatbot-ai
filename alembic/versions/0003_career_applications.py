"""Add careers applications with HR review status."""
from alembic import op
import sqlalchemy as sa

revision = "0003_career_applications"
down_revision = "0002_embedding_compatibility"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "career_applications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False, unique=True),
        sa.Column("conversation_id", sa.UUID(), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("position", sa.String(160), nullable=False),
        sa.Column("qualification", sa.String(200), nullable=False),
        sa.Column("experience_years", sa.String(40), nullable=False),
        sa.Column("skills", sa.Text(), nullable=False),
        sa.Column("current_location", sa.String(160), nullable=False),
        sa.Column("notice_period", sa.String(100), nullable=False),
        sa.Column("current_company", sa.String(160)),
        sa.Column("message", sa.Text()),
        sa.Column("resume_filename", sa.String(255), nullable=False),
        sa.Column("resume_content_type", sa.String(100), nullable=False),
        sa.Column("resume_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("resume_content", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="new_hr_review"),
        sa.Column("consent_to_contact", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_career_applications_email", "career_applications", ["email"])
    op.create_index("ix_career_applications_status_created", "career_applications", ["status", "created_at"])


def downgrade():
    op.drop_table("career_applications")
