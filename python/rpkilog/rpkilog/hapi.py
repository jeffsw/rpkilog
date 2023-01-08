'''
HTTP API with AWS lambda entry-point
'''
import base64
from datetime import datetime
import json
import logging
import os

import boto3
import netaddr
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

logger = logging.getLogger(__name__)

def aws_lambda_entry_point(event:dict, context:dict):
    #TODO: do I need the timestamp in cloudwatch? decide when testing
    logging.basicConfig(
        datefmt='%Y-%m-%dT%H:%M:%S',
        format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
    )
    if not isinstance(event, dict):
        raise TypeError(f'event argument expected to be a dict but it is a {type(event)}')
    if 'rawPath' in event:
        logger.info(f'event.rawPath: {event["rawPath"]}')
    if 'body' not in event:
        raise KeyError('event argument is missing the "body" key')
    if event.get('isBase64Encoded', False) == True:
        body_plain = base64.b64decode(event['body'])
    else:
        body_plain = event['body']
    body_dict = json.loads(body_plain)

    query_args = dict()
    query_args['prefix'] = netaddr.IPNetwork(body_dict['prefix'])
    for bool_arg_name in ['exact', 'max_len']:
        if bool_arg_name not in body_dict:
            continue
        if type(body_dict[bool_arg_name]) != bool:
            wrong_type = type(body_dict[bool_arg_name])
            raise TypeError(f'argument {bool_arg_name} must be a boolean.  Its type is {wrong_type}')
        query_args[bool_arg_name] = body_dict[bool_arg_name]
    for int_arg_name in ['max_len']:
        if int_arg_name not in body_dict:
            continue
        if type(body_dict[int_arg_name]) != int:
            wrong_type = type(body_dict[int_arg_name])
            raise TypeError(f'argument {int_arg_name} must be an int.  Its type is {wrong_type}')
        query_args[int_arg_name] = body_dict[int_arg_name]

    if 'prefix' in body_dict:
        get_history_for_prefix(**query_args)

def cli_entry_point():
    import argparse
    import dateutil.parser

    date_parser = dateutil.parser.parser()
    ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    ap.add_argument('prefix', type=netaddr.IPNetwork, help='Query the DB for given prefix')
    ap.add_argument('--exact', default=False, action='store_true', help='Exact prefix-length matches only')
    ap.add_argument('--max-len', default=None, type=int, help='Maximum prefix-length')
    ap.add_argument('--observation-timestamp-start', type=date_parser.parse, help='Optional start time for DB query')
    ap.add_argument('--observation-timestamp-end', type=date_parser.parse, help='Optional end time for DB query')
    ap.add_argument('--debug', action='store_true', help='Break to debugger immediately after argument parsing')
    args = vars(ap.parse_args())
    if args.get('debug', False):
        import pdb
        pdb.set_trace()
        args.pop('debug')

    result = get_history_for_prefix(**args)
    pretty_result = pretty_stringify_es_result(result)
    print(pretty_result)

def datetime_to_es_format(d:datetime):
    '''
    > from datetime import datetime
    > d1 = datetime(year=1981, month=10, day=26, hour=0, minute=1, second=2, microsecond=345678)
    > datetime_to_es_format(d=d1)
    '1981-10-26T00:01:02.346'
    '''
    retstr = d.strftime('%Y-%m-%dT%H:%M:%S.') + F'{d.microsecond/1000:03.0f}'
    return retstr

def get_es_client(
    aws_region:str = os.getenv('AWS_REGION'),
    es_host:str = os.getenv('RPKILOG_ES_HOST', 'es-prod.rpkilog.com'),
    timeout : int = 30,
):
    '''
    > es = get_es_client(boto3.Session().get_credentials(), aws_region='us-east-1', 'es-prod.rpkilog.com')
    '''

    aws_credentials = boto3.Session().get_credentials()

    awsauth = AWS4Auth(
        aws_credentials.access_key,
        aws_credentials.secret_key,
        aws_region,
        'es',
        session_token = aws_credentials.token,
    )
    es = OpenSearch(
        hosts = [
            {'host': es_host, 'port': 443},
        ],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout = timeout,
    )
    return es

def get_es_query_for_ip_prefix(
    prefix: netaddr.IPNetwork,
    exact: bool = None,
    max_len: int = None,
    observation_timestamp_start: datetime = None,
    observation_timestamp_end: datetime = None,
    paginate_size: int = 20,
    search_after: list = None,
):
    if bool(exact):
        raise ValueError(F'UNIMPLEMENTED: exact not yet supported')
    if max_len != None:
        raise ValueError(F'UNIMPLEMENTED: max_len not yet supported')

    # ES query actually needs the first & last addresses in the prefix, not the CIDR format.
    # For example, prefix_first_addr: 192.0.2.0 prefix_last_addr: 192.0.2.255
    prefix_first_addr = netaddr.IPAddress(prefix.first)
    prefix_last_addr = netaddr.IPAddress(prefix.last)
    # ES documentation: https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html
    query = {
        # pagination:
        # https://www.elastic.co/guide/en/elasticsearch/reference/current/paginate-search-results.html
        'size': paginate_size,
        'query': {
            'bool': {
                'filter': [
                    {
                        'range': {
                            'observation_timestamp': {
                                'format': 'strict_date_optional_time',
                                'gte': '1981-10-26T00:00:00.000Z',
                                'lte': '2035-01-01T00:00:00.000Z'
                            }
                        }
                    }
                ],
                'filter': [
                    {
                        'query_string': {
                            'analyze_wildcard': 'true',
                            'query': f'prefix: ["{str(prefix_first_addr)}" TO "{str(prefix_last_addr)}"]',
                            'time_zone': 'UTC'
                        }
                    }
                ]
            }
        },
        # sorting docs https://www.elastic.co/guide/en/elasticsearch/reference/current/sort-search-results.html
        'sort': [
            {'observation_timestamp': 'desc'},
            {'_doc': 'asc'}
        ],
    }
    # ES query timestamps are like 2022-10-30T18:35:00.123Z
    # Default values (year 1981 & 2035) are used for the timestamp range in the above query dict.
    # If this function was invoked with non-None start/end values, we update the query, below.
    if observation_timestamp_start != None:
        obs_ts_start_str = datetime_to_es_format(observation_timestamp_start)
        query['query']['bool']['filter'][0]['range']['observation_timestamp']['gte'] = obs_ts_start_str
    if observation_timestamp_end != None:
        obs_ts_end_str = datetime_to_es_format(observation_timestamp_end)
        query['query']['bool']['filter'][0]['range']['observation_timestamp']['lte'] = obs_ts_end_str
    # Pagination support uses sort_after to continue retrieving records after previous page
    if search_after != None:
        if len(search_after) != 2 or type(search_after[0]) != int or type(search_after[1]) != int:
            raise TypeError('search_after must be a list containing two integers obtained from "sort" ' +
                'key of previously-returned record'
            )
        query['search_after'] = search_after

    return query

def get_history_for_prefix(
    prefix:netaddr.IPNetwork,
    exact: bool = None,
    max_len: int = None,
    observation_timestamp_start: datetime = None,
    observation_timestamp_end: datetime = None,
):
    es_query = get_es_query_for_ip_prefix(
        prefix = prefix,
        exact = exact,
        max_len = max_len,
        observation_timestamp_start = observation_timestamp_start,
        observation_timestamp_end = observation_timestamp_end,
    )
    retval = invoke_es_query(query=es_query)
    return retval

def invoke_es_query(query):
    #TODO: get_es_client needs arguments!
    es_client = get_es_client()
    qresult = es_client.search(
        body = query,
        index = 'diff-*',
    )
    logger.info({
        'took': qresult['took'],
        'hits.total': qresult['hits']['total'],
    })
    return qresult

def pretty_stringify_es_result(es_result:dict):
    '''
    Given an ES query-response dict, stringify it with one result record per line, and indentation.
    '''
    import copy

    # emit all the summary key/value pairs here using json.dump but strip off the last '}\n'
    es_copy = copy.deepcopy(es_result)
    hits_record_list = es_copy['hits'].pop('hits')
    # we need the hits summary to be the last dict-key, so we just remove and re-add it
    es_copy['hits'] = es_copy.pop('hits', {})
    retstr = json.dumps(es_copy, indent=4)
    # strip off some closing curly-braces
    retstr = retstr[:-8]

    retstr += ',\n        "hits": [\n'
    # emit the result records, using join to ensure commas are at the end of each line
    record_strings = []
    for hit in hits_record_list:
        record_strings.append('            ' + json.dumps(hit, sort_keys=True, indent=None))
    retstr += ',\n'.join(record_strings)

    # emit the last }\n
    retstr += '\n        ]\n    }\n}\n'

    return retstr
