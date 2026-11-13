"""Subscriptions, private bot state, durable digest queue and moderation lock."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("moderated_at", sa.DateTime(timezone=True)))
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False, index=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("telegram_id", sa.BigInteger()),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "next_digest_at", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.UniqueConstraint("owner_hash", "channel"),
    )
    op.create_table(
        "bot_dialogs",
        sa.Column("owner_hash", sa.String(64), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "digest_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "subscription_id",
            sa.String(36),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subscription_id", "day"),
    )


def downgrade():
    op.drop_table("digest_deliveries")
    op.drop_table("bot_dialogs")
    op.drop_table("subscriptions")
    op.drop_column("events", "moderated_at")
