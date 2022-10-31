'''
HTTP API with AWS lambda entry-point
'''
import base64
from datetime import datetime
import json
import logging

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
    if 'prefix' in body_dict:
        get_history_for_prefix()

def datetime_to_es_format(d:datetime):
    '''
    > from datetime import datetime
    > d1 = datetime(year=1981, month=10, day=26, hour=0, minute=1, second=2, microsecond=345678)
    > datetime_to_es_format(d=d1)
    '1981-10-26T00:01:02.346'
    '''
    retstr = d.strftime('%Y-%m-%dT%H:%M:%S.') + F'{d.microsecond/1000:03.0f}'
    return retstr

def get_es_client(aws_credentials, aws_region:str, es_host:str):
    '''
    > es = get_es_client(boto3.Session().get_credentials, aws_region='us-east-1', 'es-prod.rpkilog.com')
    '''
    awsauth = AWS4Auth(
        aws_credentials.access_key,
        aws_credentials.secret_key,
        aws_region,
        'es',
        aws_credentials.token,
    )
    es = OpenSearch(
        hosts = [
            {'host': es_host, 'port': 443},
        ],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )
    return es

def get_es_query_for_ip_prefix(
    prefix: netaddr.IPNetwork,
    exact: bool = None,
    max_len: int = None,
    observation_timestamp_start: datetime = None,
    observation_timestamp_end: datetime = None,
):
    if bool(exact):
        raise ValueError(F'UNIMPLEMENTED: exact not yet supported')
    if max_len != None:
        raise ValueError(F'UNIMPLEMENTED: max_len not yet supported')

    # ES query actually needs the first & last addresses in the prefix, not the CIDR format.
    # For example, prefix_first_addr: 192.0.2.0 prefix_last_addr: 192.0.2.255
    prefix_first_addr = netaddr.IPAddress(prefix.first)
    prefix_last_addr = netaddr.IPAddress(prefix.last)
    query = {
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
                'must': [
                    {
                        'query_string': {
                            'analyze_wildcard': 'true',
                            'query': f'prefix: ["{str(prefix_first_addr)}" TO "{str(prefix_last_addr)}"]',
                            'time_zone': 'UTC'
                        }
                    }
                ]
            }
        }
    }
    # ES query timestamps are like 2022-10-30T18:35:00.123Z
    # Default values (year 1981 & 2035) are used for the timestamp range in the above query dict.
    # If this function was invoked with non-None start/end values, we update the query, below.
    if observation_timestamp_start != None:
        obs_ts_start_str = datetime_to_es_format(observation_timestamp_start)
        query['query']['bool']['filter']['range']['observation_timestamp']['gte'] = obs_ts_start_str
    if observation_timestamp_end != None:
        obs_ts_end_str = datetime_to_es_format(observation_timestamp_end)
        query['query']['bool']['filter']['range']['observation_timestamp']['lte'] = obs_ts_end_str

    return query

def get_history_for_prefix(
    prefix:netaddr.IPNetwork,
    exact: bool = None,
    max_len: int = None,
    observation_timestamp_start: datetime = None,
    observation_timestamp_end: datetime = None,
):
    #TODO: get the needed ES query
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
    qresult = es_client.search(query)
    logger.info({
        'took': qresult['took'],
        'hits.total': qresult['hits']['total'],
    })
    return qresult
