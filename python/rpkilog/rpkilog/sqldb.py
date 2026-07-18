"""
Shared SQL-database CLI helpers: connection handling and startup-argument logging, used by the
reconcile and archive-site-crawler entry points.

This module must stay dependency-light and must NOT import the CLI modules: reconcile.py imports
ArchiveSiteCrawler (for derive_tar_url()), and the crawler needs these helpers too, so hosting
them in either CLI module would create a circular import.
"""
import argparse
import logging
import os

import mariadb

from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_type import DataFileType

logger = logging.getLogger(__name__)


def db_connect(args: argparse.Namespace) -> mariadb.SyncConnection:
    """
    Connect to MariaDB using args.db_* and make the connection available to the SQL-row classes.

    The password comes from args.db_password, falling back to env RPKILOG_DB_PASSWORD.

    TODO: prod will use RDS IAM auth tokens instead of a static password

    TOTEST:
    - test_db_connect_password_falls_back_to_env: args.db_password unset + RPKILOG_DB_PASSWORD
      set connects using the env value (mariadb.connect monkeypatched)
    - test_db_connect_cli_password_beats_env: an explicit --db-password wins over the env var
    - test_db_connect_sets_default_db_connections: DataFileSource.default_db_connection and
      DataFileType.default_db_connection are the returned connection afterward
    """
    password = args.db_password
    if password is None:
        password = os.environ.get('RPKILOG_DB_PASSWORD')
    retval = mariadb.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=password,
        database=args.db_name,
        autocommit=True,
    )
    DataFileSource.default_db_connection = retval
    DataFileType.default_db_connection = retval
    return retval


def log_startup_args(args: argparse.Namespace, secret_dests: set[str]):
    """
    Log the parsed CLI arguments at INFO except those in secret_dests
    """
    parts = []
    for dest in sorted(vars(args)):
        value = getattr(args, dest)
        if dest in secret_dests and value is not None:
            value_repr = "'<redacted>'"
        else:
            value_repr = repr(value)
        parts.append(f'{dest}={value_repr}')
    logger.info('invoked with args: ' + ' '.join(parts))
