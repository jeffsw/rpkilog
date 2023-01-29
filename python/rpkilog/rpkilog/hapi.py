'''
HTTP API with AWS lambda entry-point
'''
import base64
from datetime import datetime
import dateutil.parser
import json
import logging
import os

import boto3
import netaddr
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

date_parser = dateutil.parser.parser()
logger = logging.getLogger(__name__)

def aws_lambda_entry_point(event:dict, context:dict):
    global date_parser
    # AWS Lambda runtime performs a basicConfig before we get the chance.  Override it with force=True.
    logging.basicConfig(
        datefmt='%Y-%m-%dT%H:%M:%S',
        format=f'{context.aws_request_id} %(levelname)s %(filename)s:%(lineno)d %(funcName)s %(message)s',
        force=True,
    )
    if not isinstance(event, dict):
        raise TypeError(f'event argument expected to be a dict but it is a {type(event)}')

    request_source_ip = event.get('requestContext', {}).get('http', {}).get('sourceIp', None)
    logger.info(f'request from sourceIp {request_source_ip} queryStringParameters: {event["queryStringParameters"]}')

    query_args = dict()

    if 'asn' in event['queryStringParameters']:
        query_args['asn'] = int(event['queryStringParameters']['asn'])

    if 'exact' in event['queryStringParameters']:
        query_args['exact'] = bool(event['queryStringParameters']['exact'])

    if 'max_len' in event['queryStringParameters']:
        query_args['max_len'] = int(event['queryStringParameters']['max_len'])

    if 'prefix' in event['queryStringParameters']:
        query_args['prefix'] = netaddr.IPNetwork(event['queryStringParameters']['prefix'])

    for arg_name in ['observation_timestamp_start', 'observation_timestamp_end']:
        if arg_name in event['queryStringParameters']:
            query_args[arg_name] = date_parser.parse(event['queryStringParameters'][arg_name])

    if not ('asn' in query_args or 'prefix' in query_args):
        return {
            'statusCode': 400,
            'body': 'Both asn and prefix arguments missing from request.  At least one of them is required.',
        }

    query = get_history_es_query(**query_args)
    result = invoke_es_query(query)
    # AWS REST API (APIGW 1.0) requires older response format
    # https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html#http-api-develop-integrations-lambda.response
    return {
        'isBase64Encoded': False,
        'statusCode': 200,
        'body': json.dumps(result),
    }

def cli_entry_point():
    global date_parser
    import argparse

    ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    ap.add_argument('--asn', type=int, help='Query for given ASN')
    ap.add_argument('--prefix', type=netaddr.IPNetwork, help='Query the DB for given prefix')
    ap.add_argument('--exact', action='store_true', help='Exact prefix-length matches only')
    ap.add_argument('--max-len', type=int, help='Maximum prefix-length')
    ap.add_argument('--observation-timestamp-start', type=date_parser.parse, help='Optional start time for DB query')
    ap.add_argument('--observation-timestamp-end', type=date_parser.parse, help='Optional end time for DB query')
    ap.add_argument('--debug', action='store_true', help='Break to debugger immediately after argument parsing')
    args = vars(ap.parse_args())
    if args.get('debug', False):
        import pdb
        pdb.set_trace()
        args.pop('debug')

    query = get_history_es_query(**args)
    result = invoke_es_query(query)
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
) -> dict:
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

def get_history_es_query(
    asn: int = None,
    exact: bool = None,
    max_len: int = None,
    observation_timestamp_start: datetime = None,
    observation_timestamp_end: datetime = None,
    paginate_size: int = 20,
    prefix: netaddr.IPNetwork = None,
    search_after: list = None,
    verb: str = None,
) -> dict:
    if bool(exact):
        raise ValueError(f'UNIMPLEMENTED: exact not yet supported')
    if max_len != None:
        raise ValueError(f'UNIMPLEMENTED: max_len not yet supported')
    
    # query must include at least a prefix or an asn
    if asn == None and prefix == None:
        raise KeyError(f'NOT ENOUGH ARGUMENTS: query must include at least a prefix OR asn.  Both are missing.')

    query = {
        'size': paginate_size,
        'query': {
            'bool': {
                'filter': [
                    # Add filters here
                ]
            }
        },
        # sorting docs https://www.elastic.co/guide/en/elasticsearch/reference/current/sort-search-results.html
        'sort': [
            {'observation_timestamp': 'desc'},
            {'_doc': 'asc'}
        ],
    }
    filter_list = query['query']['bool']['filter']

    if asn != None:
        filter_list.append({
            'query_string': {
                'analyze_wildcard': 'true',
                'query': f'asn:{asn}',
            }
        })

    if prefix != None:
        prefix_first_addr = netaddr.IPAddress(prefix.first)
        prefix_last_addr = netaddr.IPAddress(prefix.last)
        filter_list.append({
            'query_string': {
                'analyze_wildcard': 'true',
                'query': f'prefix: ["{str(prefix_first_addr)}" TO "{str(prefix_last_addr)}"]',
                'time_zone': 'UTC',
            }
        })

    if observation_timestamp_start != None or observation_timestamp_end != None:
        if observation_timestamp_start != None:
            obs_ts_start_str = datetime_to_es_format(observation_timestamp_start)
        else:
            obs_ts_start_str = '1981-10-26T00:00:00.000Z'
        if observation_timestamp_end != None:
            obs_ts_end_str = datetime_to_es_format(observation_timestamp_end)
        else:
            obs_ts_end_str = '2038-01-01T00:00:00.000Z'
        filter_list.append({
            'range': {
                'observation_timestamp': {
                    'format': 'strict_date_optional_time',
                    'gte': obs_ts_start_str,
                    'lte': obs_ts_end_str,
                }
            }
        })
    
    if search_after != None:
        assert(len(search_after))
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

def invoke_es_query(query) -> dict:
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
