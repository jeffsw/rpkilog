from setuptools import find_packages, setup

setup(
    version='0.23022001',
    name = 'rpkilog',
    author = 'Jeff Wheeler',
    author_email = 'jeffsw6@gmail.com',
    url = 'https://github.com/jeffsw/rpkilog/python/rpkilog/',
    description = 'RPKI log utilities',
    keywords = [
        'BGP',
        'RPKI',
    ],
    packages = find_packages(),
    install_requires = [
        'boto3',
        'netaddr',
        'opensearch-py',
        'psutil',
        'python-dateutil',
        'pyyaml',
        'requests',
        'requests_aws4auth',
        'tqdm',
    ],
    entry_points = {
        'console_scripts': [
            'rpkilog-archive-site-crawler = rpkilog.archive_site_crawler:ArchiveSiteCrawler.cli_entry_point',
            'rpkilog-diff-import = rpkilog:VrpDiff.cli_entry_point_import',
            'rpkilog-ingest-tar = rpkilog:IngestTar.cli_entry_point',
            'rpkilog-hapi = rpkilog.hapi:cli_entry_point',
            'rpkilog-vrp-cache-differ = rpkilog:VrpDiff.cli_entry_point',
        ]
    },
)
