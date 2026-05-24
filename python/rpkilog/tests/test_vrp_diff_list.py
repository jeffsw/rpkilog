"""
Tests for vrp_diff_list() and its wrapper (for e2e tests) vrp_diff_from_files()

There are synthetic tests calling vrp_diff_list() using only data in this file.

We also perform a vrp_diff_from_files() using the following golden test data files (slow):
  * old snapshot file rpkiclient_summary_20250720T093135Z.json.bz2
  * new snapshot file rpkiclient_summary_20250720T100145Z.json.bz2
  * verified correct diff file rpkiclient_vrpdiff_20250720T100145Z.json.bz2
"""
import bz2
import copy
import json
import tempfile
import time
from pathlib import Path

import pytest

from rpkilog.vrp_diff import VrpDiff

TEST_DATA_DIR = Path(__file__).parent.parent.parent.parent / 'test_data'

# ASN 64496 is the stable "UNCHANGED" ROA present in both old and new in most tests.
# ASNs 64497-64499 are used for per-test additions (DELETE / NEW / REPLACE).
BASE_ROAS = [
    {'asn': 64496, 'prefix': '192.0.2.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000},
]


def test_identical_lists_return_empty():
    result = VrpDiff.vrp_diff_list(
        old_roas=copy.deepcopy(BASE_ROAS),
        new_roas=copy.deepcopy(BASE_ROAS),
    )
    assert result == []


def test_old_only_roa_emits_delete():
    delete_roa = {'asn': 64497, 'prefix': '198.51.100.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    result = VrpDiff.vrp_diff_list(
        old_roas=copy.deepcopy(BASE_ROAS) + [delete_roa],
        new_roas=copy.deepcopy(BASE_ROAS),
    )
    assert len(result) == 1
    assert result[0].verb == 'DELETE'


def test_new_only_roa_emits_new():
    new_roa = {'asn': 64497, 'prefix': '198.51.100.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    result = VrpDiff.vrp_diff_list(
        old_roas=copy.deepcopy(BASE_ROAS),
        new_roas=copy.deepcopy(BASE_ROAS) + [new_roa],
    )
    assert len(result) == 1
    assert result[0].verb == 'NEW'


def test_same_primary_key_different_expires_emits_replace():
    old_roa = {'asn': 64497, 'prefix': '198.51.100.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    new_roa = {'asn': 64497, 'prefix': '198.51.100.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 2000000000}
    result = VrpDiff.vrp_diff_list(
        old_roas=copy.deepcopy(BASE_ROAS) + [old_roa],
        new_roas=copy.deepcopy(BASE_ROAS) + [new_roa],
    )
    assert len(result) == 1
    assert result[0].verb == 'REPLACE'


def test_different_primary_keys_emits_delete_and_new():
    old_extra = {'asn': 64497, 'prefix': '198.51.100.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    new_extra = {'asn': 64498, 'prefix': '203.0.113.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    result = VrpDiff.vrp_diff_list(
        old_roas=copy.deepcopy(BASE_ROAS) + [old_extra],
        new_roas=copy.deepcopy(BASE_ROAS) + [new_extra],
    )
    count_delete = count_new = 0
    for d in result:
        if d.verb == 'DELETE':
            count_delete += 1
        elif d.verb == 'NEW':
            count_new += 1
    assert len(result) == 2
    assert count_delete == 1
    assert count_new == 1


def test_mixed_batch_all_verbs():
    delete_roa = {'asn': 64497, 'prefix': '198.51.100.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    new_roa    = {'asn': 64498, 'prefix': '203.0.113.0/24',  'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    replace_old = {'asn': 64499, 'prefix': '192.0.2.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 1000000000}
    replace_new = {'asn': 64499, 'prefix': '192.0.2.0/24', 'maxLength': 24, 'ta': 'test', 'expires': 2000000000}
    result = VrpDiff.vrp_diff_list(
        old_roas=copy.deepcopy(BASE_ROAS) + [delete_roa, replace_old],
        new_roas=copy.deepcopy(BASE_ROAS) + [new_roa, replace_new],
    )
    count_delete = count_new = count_replace = 0
    for d in result:
        if d.verb == 'DELETE':
            count_delete += 1
        elif d.verb == 'NEW':
            count_new += 1
        elif d.verb == 'REPLACE':
            count_replace += 1
    assert len(result) == 3
    assert count_delete == 1
    assert count_new == 1
    assert count_replace == 1


@pytest.mark.slow
def test_vrp_diff_from_files_golden():
    old_file = TEST_DATA_DIR / 'rpkiclient_summary_20250720T093135Z.json.bz2'
    new_file = TEST_DATA_DIR / 'rpkiclient_summary_20250720T100145Z.json.bz2'
    golden_file = TEST_DATA_DIR / 'rpkiclient_vrpdiff_20250720T100145Z.json.bz2'

    with bz2.open(golden_file, 'rt') as f:
        golden_data = json.load(f)
    golden_diff_count = golden_data['metadata']['diff_count']

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / 'test_output.json.bz2'
        result_metadata = VrpDiff.vrp_diff_from_files(
            old_file_path=old_file,
            new_file_path=new_file,
            output_file_path=output_path,
            realtime_initial=time.time(),
        )

        assert result_metadata['diff_count'] == golden_diff_count

        with bz2.open(output_path, 'rt') as f:
            output_data = json.load(f)
        verb_counts = {'DELETE': 0, 'NEW': 0, 'REPLACE': 0}
        for diff in output_data['vrp_diffs']:
            verb_counts[diff['verb']] += 1
        assert sum(verb_counts.values()) == result_metadata['diff_count']
