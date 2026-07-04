from datetime import datetime, timedelta, timezone

import pytest

from rpkilog.reconcile import load_reconcile_config

CONFIG = load_reconcile_config()

# metadata observed in real summary files, keyed by descriptive names
METADATA_SETS = {
    'docker_container_hex_hostname': {
        'buildmachine': 'bff19fdebc7b',
        'buildtime': datetime(2026, 7, 3, 0, 4, 55, tzinfo=timezone.utc),
        'expected_source': 'rpkiclient.rpkilog.com',
    },
    'josephine_historic_archive': {
        'buildmachine': 'josephine',
        'buildtime': datetime(2025, 7, 20, 10, 1, 43, tzinfo=timezone.utc),
        'expected_source': 'josephine.sobornost.net',
    },
}


@pytest.mark.parametrize('metadata_name', METADATA_SETS.keys())
def test_metadata_matches_only_its_expected_source(metadata_name):
    # multiple mappings may share a name; every mapping that matches must carry the expected name
    metadata = METADATA_SETS[metadata_name]
    matched_names = set()
    for mapping in CONFIG.buildmachine_to_source:
        if mapping.matches(metadata['buildmachine'], metadata['buildtime']):
            matched_names.add(mapping.name)
    assert matched_names == {metadata['expected_source']}


def test_no_match_before_datetime_start():
    metadata = METADATA_SETS['docker_container_hex_hostname']
    for mapping in CONFIG.buildmachine_to_source:
        if not mapping.matches(metadata['buildmachine'], metadata['buildtime']):
            continue
        before_start = mapping.datetime_start - timedelta(seconds=1)
        assert mapping.matches(metadata['buildmachine'], before_start) is False


def test_no_match_when_regex_only_partially_matches():
    # patterns are ^...$-anchored; a 13-char hex hostname must not match the 12-char pattern
    metadata = METADATA_SETS['docker_container_hex_hostname']
    thirteen_hex_chars = metadata['buildmachine'] + 'c'
    for mapping in CONFIG.buildmachine_to_source:
        assert mapping.matches(thirteen_hex_chars, metadata['buildtime']) is False


def test_matches_inclusive_range_boundaries():
    metadata = METADATA_SETS['docker_container_hex_hostname']
    for mapping in CONFIG.buildmachine_to_source:
        if not mapping.matches(metadata['buildmachine'], metadata['buildtime']):
            continue
        assert mapping.matches(metadata['buildmachine'], mapping.datetime_start) is True
        assert mapping.matches(metadata['buildmachine'], mapping.datetime_end) is True
