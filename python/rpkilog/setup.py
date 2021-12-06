from setuptools import setup, find_packages

setup(
    version='0.214900',
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
        'psutil',
        'requests',
        'pyyaml',
    ],
    entry_points = {
        'console_scripts': [
            'rpkilog-archive-site-crawler = rpkilog.archive_site_crawler:ArchiveSiteCrawler.cli_entry_point',
            'rpkilog-ingest-tar = rpkilog:IngestTar.cli_entry_point',
            'rpkilog-vrp-cache-differ = rpkilog:VrpDiff.cli_entry_point',
        ]
    },
)
