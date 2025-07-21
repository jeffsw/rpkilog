"""
This file contains tests for some legacy code which is being refactored.

Once refactored, the new tests should be organized better, and these can be deleted.
"""

import json
import os
from pathlib import Path

import pytest

import rpkilog.ingest_tar

project_dir = Path(__file__).parent.parent.parent.parent
test_data_dir = Path(project_dir, 'test_data')

test_snapshot_files = list(test_data_dir.glob('rpkiclient_snapshot_*'))
test_summary_files = list(test_data_dir.glob('rpkiclient_summary_*'))


@pytest.fixture(scope='module', params=test_snapshot_files)
def rpkiclient_snapshot_filepath(request) -> Path:
    """
    Return a filename
    """
    return request.param


def test_summarize(rpkiclient_snapshot_filepath: Path, tmp_path: Path):
    """
    Given the path to an rpkiclient snapshot file, extract a non-empty summary.
    """
    summary_filepath = rpkilog.ingest_tar.IngestTar.extract_useful_json(
        input_tar=rpkiclient_snapshot_filepath,
        json_data_dir=tmp_path
    )
    stat_result = os.stat(summary_filepath)
    assert 1_000_000 < stat_result.st_size < 1_000_000_000, "ensure snapshot.json file is reasonable size (100MB - 1GB)"
    fh = open(summary_filepath)
    json_data = json.load(fh)
    assert json_data['metadata']['uniquevrps'] > 100_000
    assert len(json_data['roas']) == json_data['metadata']['uniquevrps']

# TODO: add a test of vrp_diff_from_files using a pair of canned summary files and an expected diff file for comparison
