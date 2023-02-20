'''
HTTP API with AWS lambda entry-point
'''
import base64
from datetime import datetime
import dateutil.parser
import json
import logging
import os
import re

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

    if 'paginate_size' in event['queryStringParameters']:
        query_args['paginate_size'] = int(event['queryStringParameters'])

    if 'prefix' in event['queryStringParameters']:
        query_args['prefix'] = netaddr.IPNetwork(event['queryStringParameters']['prefix'])

    if 'search_after' in event['queryStringParameters']:
        # search_after must be an integer, a comma, then a second integer; e.g. 1675074991000,7694822
        if rem := re.match('^(\d+),(\d+)$', event['queryStringParameters']['search_after']):
            query_args['search_after'] = [int(rem.group(1)), int(rem.group(2))]
        else:
            raise ValueError('search_after argument must be formatted like: 1675074991000,7694822')

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
        'headers': {
            'Access-Control-Allow-Methods': 'GET,OPTIONS,POST',
            'Access-Control-Allow-Origin': '*',
        },
        'isBase64Encoded': False,
        'statusCode': 200,
        'body': json.dumps(result),
    }

def cli_entry_point():
    global date_parser
    import argparse

    ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
    ag1 = ap.add_argument_group('search parameters')
    ag1.add_argument('--asn', type=int, help='Query for given ASN')
    ag1.add_argument('--prefix', type=netaddr.IPNetwork, help='Query the DB for given prefix')
    ag1.add_argument('--exact', action='store_true', help='Exact prefix-length matches only')
    ag1.add_argument('--max-len', type=int, help='Maximum prefix-length')
    ag1.add_argument('--observation-timestamp-start', type=date_parser.parse, help='Optional start time for DB query')
    ag1.add_argument('--observation-timestamp-end', type=date_parser.parse, help='Optional end time for DB query')
    ag3 = ap.add_argument_group('paginate')
    ag3.add_argument('--paginate-from', type=int, help='Optional offset for pagination')
    ag3.add_argument('--paginate-size', type=int, help='Number of records per page (default: 20)')
    ag3.add_argument('--search-after', help='Optional pagination cursor e.g. 1675074991000,7694822')
    ap.add_argument('--debug', action='store_true', help='Break to debugger immediately after argument parsing')
    args = vars(ap.parse_args())
    if args.get('debug', False):
        import pdb
        pdb.set_trace()
        args.pop('debug')
    if 'search_after' in args:
        # search_after must be an integer, a comma, then a second integer; e.g. 1675074991000,7694822
        if rem := re.match('^(\d+),(\d+)$', args['search_after']):
            args['search_after'] = [int(rem.group(1)), int(rem.group(2))]
        else:
            raise ValueError('--search-after argument must be formatted like: 1675074991000,7694822')

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
    aws_region:str = os.getenv('AWS_REGION', 'us-east-1'),
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

def get_history_es_query(
    asn: int = None,
    exact: bool = None,
    max_len: int = None,
    observation_timestamp_start: datetime = None,
    observation_timestamp_end: datetime = None,
    paginate_from: int = None,
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

    if paginate_from != None:
        query['from'] = int(paginate_from)

    if search_after != None:
        # Pagination support uses sort_after to continue retrieving records after previous page
        if len(search_after) == 2 and type(search_after[0]) == int and type(search_after[1]) == int:
            query['search_after'] = [
                jstime_to_es_no_millis_format(search_after[0]),
                search_after[1]
            ]
        else:
            raise TypeError('search_after must be a list containing two integers obtained from "sort" ' +
                'key of previously-returned record'
            )

    return query

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

def jstime_to_es_no_millis_format(jstime:int) -> str:
    '''
    Convert argument in JavaScript time format (milliseconds since epoch) to ElasticSearch format.

    >>> jstime_to_es_format(1672000541000)
    '2022-12-25T15:35:41.000'
    '''
    dt = datetime.fromtimestamp(jstime / 1000)
    retstr = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return retstr

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
