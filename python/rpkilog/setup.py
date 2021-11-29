from setuptools import setup, find_packages

setup(
    version='0.214700',
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
        'netaddr',
        'psutil',
    ],
    entry_points = {
        'console_scripts': [
            'rpkilog-ingest-tar = rpkilog:IngestTar.cli_entry_point',
            'rpki-vrp-cache-differ = rpkilog:VrpDiff.cli_entry_point',
        ]
    },
)
