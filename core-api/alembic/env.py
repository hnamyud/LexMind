from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.models import Base

config = context.config
_sync_url = make_url(get_settings().database_url).set(drivername="postgresql+psycopg")
_sync_url = _sync_url.difference_update_query(["pgbouncer", "connection_limit"])
config.set_main_option("sqlalchemy.url", _sync_url.render_as_string(hide_password=False))
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()
else:
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()
