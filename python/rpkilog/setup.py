from setuptools import setup, find_packages

setup(
    version='0.22101001',
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
        'pyyaml',
        'requests',
        'requests_aws4auth',
    ],
    entry_points = {
        'console_scripts': [
            'rpkilog-archive-site-crawler = rpkilog.archive_site_crawler:ArchiveSiteCrawler.cli_entry_point',
            'rpkilog-diff-import = rpkilog:VrpDiff.cli_entry_point_import',
            'rpkilog-ingest-tar = rpkilog:IngestTar.cli_entry_point',
            'rpkilog-vrp-cache-differ = rpkilog:VrpDiff.cli_entry_point',
        ]
    },
)
