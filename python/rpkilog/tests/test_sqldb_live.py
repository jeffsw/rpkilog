"""
Live (network) test: prove the pure-Python mariadb driver plus our mysql_clear_password plugin
authenticate to the real RDS instance with an IAM auth token.  Gated behind RPKILOG_LIVE_DB_*
environment variables because it needs AWS credentials, database Security Group access, and the
live database: the db-connect CI job sets them (see ci-python.yml); everywhere else this skips.

The github_ci DB user has no grants (USAGE only), so the test connects without a default
database and proves login only.
"""
import os
from argparse import Namespace

import pytest

from rpkilog import sqldb

pytestmark = pytest.mark.skipif(
    os.environ.get('RPKILOG_LIVE_DB_HOST') is None,
    reason='live DB test runs only when RPKILOG_LIVE_DB_* env vars are set (see ci-python.yml)',
)


def test_db_connect_iam_live():
    args = Namespace(
        db_host=os.environ['RPKILOG_LIVE_DB_HOST'],
        db_iam_auth=True,
        db_name=os.environ.get('RPKILOG_LIVE_DB_NAME'),
        db_password=None,
        db_port=3306,
        db_ssl_ca=os.environ.get('RPKILOG_LIVE_DB_SSL_CA'),
        db_user=os.environ.get('RPKILOG_LIVE_DB_USER', 'github_ci'),
    )
    conn = sqldb.db_connect(args)
    cursor = conn.cursor()
    cursor.execute('SELECT CURRENT_USER(), @@require_secure_transport')
    row = cursor.fetchone()
    conn.close()
    assert row[0].startswith(args.db_user + '@')
    assert row[1] == 1
