"""
Shared engine for the sql-* mise tasks (stdlib only).  The task files in .mise/tasks/ are thin
wrappers over the functions here; see tmp/plan/gh-81-inline-writers.md "Database sync" section.

Connection details (host, admin user/password) come from each root's terraform outputs, so no
credential copies live in env files.  Prod connections use TLS with the RDS CA bundle
(downloaded on first use into the dump directory as a dotfile).  Loads restore over a
dropped-and-recreated database, then run `atlas migrate apply` to replay any migrations the
source didn't have -- correct because the dump carries `atlas_schema_revisions`.
"""
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATABASE = 'rpkilog'
DB_PORT = 3306
CLIENT_VERSION_FLOOR = (10, 11)
RDS_CA_URL = 'https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem'
RDS_CA_FILENAME = '.rds-us-east-1-bundle.pem'
HYGIENE_MAX_FILES = 10
HYGIENE_MAX_AGE_DAYS = 35

# Which terraform root supplies each environment's connection details, and the output names
# there (dev and prod name their outputs differently).
ENVIRONMENTS = {
    'dev': {
        'tf_root': 'terraform/root/dev',
        'output_host': 'mariadb_1_endpoint',
        'output_user': 'mariadb_1_admin_username',
        'output_password': 'mariadb_1_admin_password',
        'tls': False,
    },
    'prod': {
        'tf_root': 'terraform/root/prod',
        'output_host': 'mariadb1_endpoint',
        'output_user': 'mariadb1_admin_username',
        'output_password': 'mariadb1_admin_password',
        'tls': True,
    },
}

INSTALL_HINTS = (
    'install the MariaDB client:\n'
    '  macOS:         brew install mariadb\n'
    '  Debian/Ubuntu: apt install mariadb-client\n'
    '  Fedora/RHEL:   dnf install mariadb\n'
    'or, for an exact server-matched version: docker run --rm mariadb:11.8 mariadb-dump ...'
)


def project_root() -> Path:
    retval = Path(os.environ['MISE_PROJECT_ROOT'])
    return retval


def colored(text: str, ansi_code: str) -> str:
    """Wrap text in an ANSI color when stderr is a terminal."""
    if sys.stderr.isatty():
        retstr = f'\033[{ansi_code}m{text}\033[0m'
    else:
        retstr = text
    return retstr


def fail(message: str):
    print(colored(message, '31'), file=sys.stderr)
    raise SystemExit(1)


def parse_mariadb_version(version_text: str) -> tuple | None:
    """
    Extract the MariaDB version from `mariadb --version` / `mariadb-dump --version` output,
    e.g. '... Distrib 10.11.6-MariaDB ...' or 'mariadb-dump from 11.8.2-MariaDB ...'.
    Returns None when the text names no MariaDB version (e.g. a MySQL client).
    """
    match = re.search(r'(\d+)\.(\d+)\.(\d+)-MariaDB', version_text)
    if match is None:
        retval = None
    else:
        retval = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return retval


def client_check() -> int:
    """Verify the mariadb + mariadb-dump clients are present and recent enough."""
    for binary in ('mariadb', 'mariadb-dump'):
        try:
            proc = subprocess.run([binary, '--version'], capture_output=True, text=True)
        except FileNotFoundError:
            fail(f'{binary} not found on PATH; {INSTALL_HINTS}')
        version = parse_mariadb_version(proc.stdout + proc.stderr)
        if version is None:
            fail(
                f'{binary} does not appear to be a MariaDB client'
                f' (MySQL clients have known friction against MariaDB); {INSTALL_HINTS}'
            )
        if version[0:2] < CLIENT_VERSION_FLOOR:
            floor_text = '.'.join(str(part) for part in CLIENT_VERSION_FLOOR)
            fail(f'{binary} is MariaDB {version[0]}.{version[1]}; need >= {floor_text}; '
                 + INSTALL_HINTS)
        print(f'{binary}: MariaDB {version[0]}.{version[1]}.{version[2]} ok')
    return 0


def dump_dir() -> Path:
    """The dump directory (overridable via RPKILOG_SQL_DUMP_DIR), created on first use."""
    override = os.environ.get('RPKILOG_SQL_DUMP_DIR')
    if override is not None:
        retval = Path(override)
    else:
        retval = project_root() / 'tmp' / 'sql-dumps'
    retval.mkdir(parents=True, exist_ok=True)
    return retval


def tf_output(tf_root: str, output_name: str) -> str:
    proc = subprocess.run(
        ['terraform', f'-chdir={project_root() / tf_root}', 'output', '-raw', output_name],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        fail(f'terraform output {output_name} failed in {tf_root} '
             f'(is the right workspace selected?):\n{proc.stderr}')
    retstr = proc.stdout.strip()
    return retstr


def connection(environment: str) -> dict:
    """host/user/password (+ ssl_ca path for prod) for one environment, via terraform outputs."""
    config = ENVIRONMENTS[environment]
    retdict = {
        'host': tf_output(config['tf_root'], config['output_host']),
        'user': tf_output(config['tf_root'], config['output_user']),
        'password': tf_output(config['tf_root'], config['output_password']),
        'ssl_ca': None,
    }
    if config['tls']:
        ca_path = dump_dir() / RDS_CA_FILENAME
        if not ca_path.is_file():
            urllib.request.urlretrieve(RDS_CA_URL, ca_path)
        retdict['ssl_ca'] = ca_path
    return retdict


def client_args(conn: dict) -> list:
    """Common mariadb/mariadb-dump connection arguments (password goes via MYSQL_PWD, not argv)."""
    retlist = ['--host', conn['host'], '--port', str(DB_PORT), '--user', conn['user']]
    if conn['ssl_ca'] is not None:
        retlist.append(f'--ssl-ca={conn["ssl_ca"]}')
    else:
        # dev's MariaDB serves no TLS; without this, 11.4+ clients attempt TLS by default and
        # print a server-cert-verification warning on every run
        retlist.append('--skip-ssl')
    return retlist


def run_client(command: list, conn: dict, stdin_file=None):
    env = dict(os.environ)
    env['MYSQL_PWD'] = conn['password']
    proc = subprocess.run(command, env=env, stdin=stdin_file)
    if proc.returncode != 0:
        fail(f'{command[0]} failed with exit code {proc.returncode}')


def hygiene_warning():
    """
    Warn (yellow, stderr) when the dump directory holds more than HYGIENE_MAX_FILES dumps or
    any dump older than HYGIENE_MAX_AGE_DAYS, reporting disk usage; never deletes anything.
    """
    directory = dump_dir()
    now = datetime.now(timezone.utc)
    dump_files = sorted(directory.glob('*.sql'))
    total_bytes = 0
    oldest_age = timedelta(0)
    for dump_file in dump_files:
        stat = dump_file.stat()
        total_bytes += stat.st_size
        age = now - datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        if age > oldest_age:
            oldest_age = age
    problems = []
    if len(dump_files) > HYGIENE_MAX_FILES:
        problems.append(f'{len(dump_files)} dump files (more than {HYGIENE_MAX_FILES})')
    if oldest_age > timedelta(days=HYGIENE_MAX_AGE_DAYS):
        problems.append(f'oldest is {oldest_age.days} days old (more than '
                        f'{HYGIENE_MAX_AGE_DAYS} days, the RDS backup-retention window)')
    if len(problems) > 0:
        size_mib = total_bytes / (1024 * 1024)
        message = (f'WARNING: {directory} has ' + ' and '.join(problems)
                   + f', using {size_mib:.1f} MiB; consider cleaning up (nothing auto-deletes)')
        print(colored(message, '33'), file=sys.stderr)


def dump_to_file(environment: str) -> Path:
    """Dump one environment's database (including atlas_schema_revisions) to a timestamped file."""
    conn = connection(environment)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    retval = dump_dir() / f'{DATABASE}-{environment}-{timestamp}.sql'
    command = ['mariadb-dump'] + client_args(conn) + [
        '--single-transaction', '--quick', f'--result-file={retval}', DATABASE,
    ]
    print(f'dumping {environment} {DATABASE} from {conn["host"]} ...', flush=True)
    run_client(command, conn)
    size_mib = retval.stat().st_size / (1024 * 1024)
    print(f'wrote {retval} ({size_mib:.1f} MiB)', flush=True)
    hygiene_warning()
    return retval


def load_from_file(environment: str, dump_file: Path):
    """Restore a dump over a dropped-and-recreated database, then replay pending migrations."""
    if not dump_file.is_file():
        fail(f'dump file not found: {dump_file}')
    conn = connection(environment)
    print(f'loading {dump_file} into {environment} {DATABASE} on {conn["host"]} ...', flush=True)
    recreate_sql = f'DROP DATABASE IF EXISTS {DATABASE}; CREATE DATABASE {DATABASE};'
    run_client(['mariadb'] + client_args(conn) + ['-e', recreate_sql], conn)
    with open(dump_file) as stdin_file:
        run_client(['mariadb'] + client_args(conn) + [DATABASE], conn, stdin_file=stdin_file)
    atlas_migrate_apply(environment, conn)
    hygiene_warning()
    print(f'load into {environment} complete')


def atlas_migrate_apply(environment: str, conn: dict):
    """Replay any migrations the restored atlas_schema_revisions doesn't already record."""
    migration_dir = project_root() / 'terraform' / 'module' / 'sqldb_schema' / 'migrations'
    atlas_url = 'maria://{user}:{password}@{host}:{port}/{database}'.format(
        user=urllib.parse.quote(conn['user'], safe=''),
        password=urllib.parse.quote(conn['password'], safe=''),
        host=conn['host'],
        port=DB_PORT,
        database=DATABASE,
    )
    if ENVIRONMENTS[environment]['tls']:
        # matches the sqldb_schema module: RDS requires TLS; the RDS CA is not in system trust
        atlas_url += '?tls=skip-verify'
    proc = subprocess.run(
        ['atlas', 'migrate', 'apply', '--dir', f'file://{migration_dir}', '--url', atlas_url],
    )
    if proc.returncode != 0:
        fail(f'atlas migrate apply failed with exit code {proc.returncode}')


# CLI entry points for the .mise/tasks/sql-* wrappers.  The mariadb-client preflight is NOT
# called here: every wrapper task declares `#MISE depends=["sql-client-check"]`, so mise runs
# it exactly once up front.

def cli_dump(environment: str) -> int:
    dump_to_file(environment)
    return 0


def cli_load(environment: str, argv: list) -> int:
    if len(argv) != 1:
        fail(f'usage: mise run sql-load-{environment}-from-file <dump-file>')
    load_from_file(environment, Path(argv[0]))
    return 0


def cli_sync(source_environment: str, destination_environment: str) -> int:
    dump_file = dump_to_file(source_environment)
    load_from_file(destination_environment, dump_file)
    return 0
