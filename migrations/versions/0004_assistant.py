"""Private assistant state, bounded traces and a shared daily API quota."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assistant_dialogs",
        sa.Column("owner_hash", sa.String(64), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_assistant_dialogs_expires_at", "assistant_dialogs", ["expires_at"]
    )
    op.create_table(
        "assistant_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_assistant_traces_owner_hash", "assistant_traces", ["owner_hash"]
    )
    op.create_index(
        "ix_assistant_traces_created_at", "assistant_traces", ["created_at"]
    )
    op.create_table(
        "assistant_quotas",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("assistant_quotas")
    op.drop_table("assistant_traces")
    op.drop_table("assistant_dialogs")
