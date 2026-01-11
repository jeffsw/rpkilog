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


# TODO: implement below
# def test_vrp_diff_from_files(vrp_diff_test_filepath: Path):
#     """
#     Taking a vrp_diff_test.yml file as input, run vrp_diff_from_files on the given input files and
#     compare result to the given expected-output file.
#
#     Note: the reason this is one yml file per set of test data, not a big yml file with a list of all
#     the tests, is so a subset of the files could be committed to the repo and run by GHA while larger
#     tests might run only locally.
#     """
#     yaml.load(vrp_diff_test_filepath.read_text(), Loader=yaml.SafeLoader)


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
