import os
from alembic import context
from sqlalchemy import engine_from_config, pool
from kurai.models import Base

config = context.config
if os.getenv("DATABASE_URL") and not config.attributes.get("ignore_database_env"):
    config.set_main_option(
        "sqlalchemy.url", os.environ["DATABASE_URL"].replace("%", "%%")
    )
if context.is_offline_mode():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
