import logging
import os
from logging.config import fileConfig

from flask import current_app

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


def get_engine():
    try:
        # this works with Flask-SQLAlchemy<3 and Alchemical
        return current_app.extensions['migrate'].db.get_engine()
    except (TypeError, AttributeError):
        # this works with Flask-SQLAlchemy>=3
        return current_app.extensions['migrate'].db.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=True).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
config.set_main_option('sqlalchemy.url', get_engine_url())
target_db = current_app.extensions['migrate'].db

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_metadata():
    if hasattr(target_db, 'metadatas'):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=get_metadata(), literal_binds=True
    )

    with context.begin_transaction():
        context.run_migrations()


PRODUCTION_DATABASE_NAME = "appex_payroll_db_zgdz"


def enforce_production_migration_guard(connection):
    """Require explicit, database-specific confirmation for production migrations."""
    try:
        actual_database = connection.exec_driver_sql(
            "SELECT current_database()"
        ).scalar()
    finally:
        # The identity query autobegins a SQLAlchemy transaction.
        # Close that read-only transaction before Alembic starts its own.
        if connection.in_transaction():
            connection.rollback()

    app_environment = os.getenv("APP_ENV", "").strip().lower()

    is_production = (
        actual_database == PRODUCTION_DATABASE_NAME
        or app_environment == "production"
    )

    if not is_production:
        return

    if actual_database != PRODUCTION_DATABASE_NAME:
        raise RuntimeError(
            "Production migration blocked: APP_ENV is production, "
            "but the connected database does not match the verified "
            "production database identity."
        )

    allow_production = os.getenv(
        "APPEX_ALLOW_PRODUCTION_MIGRATIONS", ""
    ).strip().lower() in {"1", "true", "yes", "on"}

    expected_database = os.getenv(
        "APPEX_EXPECTED_PRODUCTION_DATABASE", ""
    ).strip()

    if not allow_production:
        raise RuntimeError(
            "Production migration blocked. Explicit approval is required "
            "through APPEX_ALLOW_PRODUCTION_MIGRATIONS=true."
        )

    if expected_database != PRODUCTION_DATABASE_NAME:
        raise RuntimeError(
            "Production migration blocked. "
            "APPEX_EXPECTED_PRODUCTION_DATABASE must exactly match "
            "the verified production database name."
        )

    if actual_database != expected_database:
        raise RuntimeError(
            "Production migration blocked: connected database identity "
            "does not match the explicitly expected database."
        )


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    conf_args = current_app.extensions['migrate'].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = get_engine()

    with connectable.connect() as connection:
        enforce_production_migration_guard(connection)
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            **conf_args
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
