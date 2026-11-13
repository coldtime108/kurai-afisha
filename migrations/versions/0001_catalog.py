"""Initial source-backed catalog, raw records and audit trail."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("normalized_title", sa.String(240), nullable=False, index=True),
        sa.Column("category", sa.String(32), nullable=False, index=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("date_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("date_end", sa.DateTime(timezone=True)), sa.Column("duration_min", sa.Integer()),
        sa.Column("city", sa.String(120), nullable=False, index=True),
        sa.Column("venue", sa.String(240), nullable=False),
        sa.Column("address", sa.String(400), nullable=False),
        sa.Column("lat", sa.Float()), sa.Column("lon", sa.Float()),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_min", sa.Integer()), sa.Column("price_max", sa.Integer()),
        sa.Column("is_free", sa.Boolean()), sa.Column("age_limit", sa.Integer()),
        sa.Column("language", sa.String(80)), sa.Column("org_link", sa.Text()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)), sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("raw_records", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_hash", sa.String(64), nullable=False, unique=True), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("audit_entries", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("actor", sa.String(60), nullable=False), sa.Column("action", sa.String(40), nullable=False), sa.Column("entity_id", sa.String(36), nullable=False), sa.Column("changes", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("feedback", sa.Column("id", sa.String(36), primary_key=True), sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="SET NULL")), sa.Column("message", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for name in ("feedback", "audit_entries", "raw_records", "events"):
        op.drop_table(name)
