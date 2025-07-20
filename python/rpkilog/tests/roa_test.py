import json
from pathlib import Path

import pytest

from rpkilog.vrp_diff import Roa


test_roa_sources = [
    {'filename': Path(__file__).with_suffix('.routinator_jsonext'), 'offset': 0},
    {'filename': Path(__file__).with_suffix('.routinator_jsonext'), 'offset': -1},
    {'filename': Path(__file__).with_suffix('.rpkiclient2021_json'), 'offset': 0},
    {'filename': Path(__file__).with_suffix('.rpkiclient2021_json'), 'offset': -1},
    {'filename': Path(__file__).with_suffix('.rpkiclient2023_json'), 'offset': 0},
    {'filename': Path(__file__).with_suffix('.rpkiclient2023_json'), 'offset': -1},
]


@pytest.fixture(scope='module', params=test_roa_sources)
def test_roa(request):
    """
    Get a test ROA from the given file and roa-array-offset.  The idea is we want to run our tests on
    data from each source of VRP data we're using.  Additionally, we might want to do some tests for IPv4
    and IPv6 or something like that.
    """
    source = request.param
    fh = open(source['filename'])
    json_data = json.load(fh)
    roa_dict = json_data['roas'][source['offset']]
    # ducktype
    if 'source' in roa_dict:
        roa_obj = Roa.new_from_routinator_jsonext(routinator_json=roa_dict)
    elif 'expires' in roa_dict:
        roa_obj = Roa.new_from_rpkiclient_json(rpkiclient_json=roa_dict)
    else:
        raise ValueError(f'unable to instantiate Roa object from configured test data: {source}')
    return roa_obj


def test_routinator_jsonext():
    data_filename = Path(__file__).with_suffix('.routinator_jsonext')
    data_fh = open(data_filename)
    data_dict = json.load(data_fh)
    for routinator_json_roa in data_dict['roas']:
        Roa.new_from_routinator_jsonext(routinator_json=routinator_json_roa)


def test_rpkiclient_2021json():
    data_filename = Path(__file__).with_suffix('.rpkiclient2021_json')
    data_fh = open(data_filename)
    data_dict = json.load(data_fh)
    for rpkiclient_json_roa in data_dict['roas']:
        Roa(**rpkiclient_json_roa)


def test_rpkiclient_2023json():
    data_filename = Path(__file__).with_suffix('.rpkiclient2023_json')
    data_fh = open(data_filename)
    data_dict = json.load(data_fh)
    for rpkiclient_json_roa in data_dict['roas']:
        Roa(**rpkiclient_json_roa)


def test_as_json_obj(test_roa):
    """
    Ensure the returned object can be serialized by the Python json library w/o any special serializers
    """
    if not isinstance(test_roa, Roa):
        raise TypeError(f'test setup problem; given test_roa is not a Roa object: {test_roa}')
    jo = test_roa.as_json_obj()
    jstr = json.dumps(jo)
    _ = jstr


def test_as_json_str(test_roa):
    jstr = test_roa.as_json_str()
    assert isinstance(jstr, str)


def test_eq(test_roa):
    assert test_roa == test_roa


def test_primary_key(test_roa):
    pk = test_roa.primary_key()
    _ = pk


def test_sortable(test_roa):
    sortable_tuple = test_roa.sortable()
    _ = sortable_tuple
