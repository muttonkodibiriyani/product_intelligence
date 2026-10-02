"""Alembic environment: plain SQL migrations, no ORM metadata autogenerate."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from pi_db import database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = config.get_main_option("sqlalchemy.url") or database_url()

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
