'''
HTTP API with AWS lambda entry-point
'''
from datetime import datetime
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
import netaddr
from requests_aws4auth import AWS4Auth

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
    raise ValueError(F'UNIMPLEMENTED: Need to convert prefix argument into the below format')
    if exact == None:
        exact = False
    elif exact == True:
        raise ValueError(F'UNIMPLEMENTED: exact not yet supported')
    if max_len != None:
        raise ValueError(F'UNIMPLEMENTED: max_len not yet supported')
    observation_timestamp_start = datetime_to_es_format(observation_timestamp_start)
    observation_timestamp_end = datetime_to_es_format(observation_timestamp_end)
    query = {
        'query': {
            'bool': {
                'filter': [
                    {
                        'range': {
                            'observation_timestamp': {
                                'format': 'strict_date_optional_time',
                                'gte': '2022-01-31T00:00:00.000Z',
                                'lte': '2030-01-01T00:00:00.000Z'
                            }
                        }
                    }
                ],
                'must': [
                    {
                        'query_string': {
                            'analyze_wildcard': 'true',
                            'query': 'prefix: ["1.6.0.0" TO "1.7.255.255"]',
                            'time_zone': 'UTC'
                        }
                    }
                ]
            }
        }
    }
    return query
