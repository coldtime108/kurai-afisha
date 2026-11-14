"""Collection runs, actual source snapshots and stable source-to-event mappings."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_collection_runs_status", "collection_runs", ["status"])
    op.create_table(
        "source_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("body_gzip", sa.LargeBinary(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("url", "content_hash"),
    )
    op.create_index("ix_source_pages_source_id", "source_pages", ["source_id"])
    op.create_index("ix_source_pages_fetched_at", "source_pages", ["fetched_at"])
    op.create_table(
        "collected_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(1000), nullable=False),
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="SET NULL")
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("reviewed_hash", sa.String(64)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    op.create_index("ix_collected_items_source_id", "collected_items", ["source_id"])


def downgrade():
    op.drop_table("collected_items")
    op.drop_table("source_pages")
    op.drop_table("collection_runs")
