"""Track publication separately from the creation of an internal draft."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("published_at", sa.DateTime(timezone=True)))
    # Preserve the age of existing public data; migration must not announce it as new.
    events = sa.table(
        "events", sa.column("status"), sa.column("created_at"), sa.column("published_at")
    )
    op.execute(
        events.update().where(events.c.status == "published").values(
            published_at=events.c.created_at
        )
    )
    op.create_index("ix_events_published_at", "events", ["published_at"])


def downgrade():
    op.drop_index("ix_events_published_at", table_name="events")
    op.drop_column("events", "published_at")
