#!/usr/bin/env python
import argparse
import bz2
from collections import deque
import getpass
import importlib.metadata
import json
import logging
import operator
import os
import re
import socket
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
import dateutil.parser
import netaddr
import opensearchpy.helpers
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from tqdm import tqdm

from rpkilog.collision_behavior import CollisionBehavior
from rpkilog.process_snapshot_summary_queue import receive_all_messages, s3_events_from_message
from rpkilog.roa import Roa
from rpkilog.util import list_s3_object_previous

logger = logging.getLogger(__name__)


class VrpDiff():
    def __init__(self, old_roa:Roa, new_roa:Roa):
        if not (isinstance(old_roa, Roa) or old_roa==None):
            raise TypeError(F'Argument old_roa should be an Roa (or None) but it is a {type(old_roa)}')
        if not (isinstance(new_roa, Roa) or new_roa==None):
            raise TypeError(F'Argument new_roa should be an Roa (or None) but it is a {type(new_roa)}')
        self.old_roa = old_roa
        self.new_roa = new_roa
        if old_roa != None and new_roa == None:
            self.verb = 'DELETE'
        elif old_roa != None and new_roa != None:
            if old_roa == new_roa:
                self.verb = 'UNCHANGED'
            else:
                self.verb = 'REPLACE'
        elif old_roa == None and new_roa != None:
            self.verb = 'NEW'
        else:
            raise

    def as_json_obj(self):
        '''
        Return a dict able to be serialized by the default json.dump serializer.
        '''
        retdict = {}
        retdict['verb'] = self.verb
        if self.old_roa != None:
            retdict['old_roa'] = self.old_roa.as_jdict()
        if self.new_roa != None:
            retdict['new_roa'] = self.new_roa.as_jdict()
        return retdict

    def as_json_str(self):
        '''
        Return a serialized JSON string representing the contents of the VrpDiff object-instance.
        '''
        retstr = F'{{ "verb": "{self.verb}"'
        if self.old_roa != None:
            retstr += F', "old_roa": {self.old_roa.as_json_str()}'
        if self.new_roa != None:
            retstr += F', "new_roa": {self.new_roa.as_json_str()}'
        retstr += ' }'
        return retstr

    def es_bulk_insertable_dict(self, es_index:str, diff_datetime:datetime) -> dict:
        '''
        Return a dict that may be passed to elasticsearch.helpers.bulk() to insert this diff object.
        '''
        body = self.es_insertable_body(diff_datetime=diff_datetime)
        es_doc_id = self.es_id(diff_datetime=diff_datetime)
        resdict = {
            '_op_type': 'index',
            '_index': es_index,
            '_id': es_doc_id,
            '_source': body,
        }
        return resdict

    def es_id(self, diff_datetime:datetime) -> str:
        '''
        Return a string usable as the ES DocumentID (primary key) for this diff.
        '''
        es_doc_id = '+'.join(map(str, [
            int(diff_datetime.timestamp()),
            self.get_prefix(),
            self.get_maxLength(),
            self.get_asn(),
            self.get_ta(),
        ]))
        return(es_doc_id)

    def es_insert(self, es_client:OpenSearch, es_index:str, diff_datetime:datetime):
        '''
        Insert object into given ElasticSearch index
        '''
        body = self.es_insertable_body(diff_datetime=diff_datetime)
        es_doc_id = self.es_id(diff_datetime=diff_datetime)
        result = es_client.index(
            index=es_index,
            op_type='create',
            body=body,
            id=es_doc_id,
        )
        return result

    def es_insertable_body(self, diff_datetime:datetime) -> dict:
        'Return a dict which may be inserted into ElasticSearch'
        body={
            'observation_timestamp': diff_datetime.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'verb': self.verb,
            'prefix': self.get_prefix(),
            'maxLength': self.get_maxLength(),
            'asn': self.get_asn(),
            'ta': self.get_ta(),
        }
        if self.old_roa:
            body['old_expires'] = datetime.fromtimestamp(self.old_roa.expires, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            body['old_roa'] = self.old_roa.as_json_obj()
        if self.new_roa:
            body['new_expires'] = datetime.fromtimestamp(self.new_roa.expires, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            body['new_roa'] = self.new_roa.as_json_obj()
        return body

    @classmethod
    def from_json_obj(cls, j:dict):
        '''
        Instantiate a VrpDiff object from its JSON representation
        '''
        old_roa = j.get('old_roa', None)
        if old_roa:
            old_roa = Roa(**old_roa)
        new_roa = j.get('new_roa', None)
        if new_roa:
            new_roa = Roa(**new_roa)
        o = cls(old_roa=old_roa, new_roa=new_roa)
        return o

    def get_asn(self) -> int:
        if self.new_roa!=None:
            return self.new_roa.asn
        elif self.old_roa!=None:
            return self.old_roa.asn
        else:
            raise KeyError('Missing both old_roa and new_roa.  Invalid object!')

    def get_maxLength(self) -> int:
        if self.new_roa!=None:
            return self.new_roa.maxLength
        elif self.old_roa!=None:
            return self.old_roa.maxLength
        else:
            raise KeyError('Missing both old_roa and new_roa.  Invalid object!')

    def get_prefix(self) -> str:
        if self.new_roa!=None:
            return str(self.new_roa.prefix)
        elif self.old_roa!=None:
            return str(self.old_roa.prefix)
        else:
            raise KeyError('Missing both old_roa and new_roa.  Invalid object!')

    def get_ta(self) -> str:
        if self.new_roa!=None:
            return self.new_roa.ta
        elif self.old_roa!=None:
            return self.old_roa.ta
        else:
            raise KeyError('Missing both old_roa and new_roa.  Invalid object!')

    @classmethod
    def limit_cpu_sleep(cls, invocation_time:float, limit:float):
        '''
        Sleep long enough to bring our CPU utilization (usr+sys) below given fraction of real run-time.
        For example, if we have run for 30 seconds and used 4 seconds usr+sys, and limit is 0.10 (10%),
        sleep for 10 seconds.
        Return immediately if no sleep is necessary.
        '''
        now = time.time()
        realtime_elapsed = now - invocation_time
        cpu_budget = realtime_elapsed * limit
        times = os.times()
        cpu_used = times.user + times.system
        if cpu_budget < cpu_used:
            sleep_for = cpu_used - cpu_budget
            logger.info(F'LIMIT_CPU sleeping for {sleep_for} to stay within CPU budget of {limit*100}%')
            time.sleep(sleep_for)

    @classmethod
    def vrp_diff_from_files(
        cls,
        old_file_path:Path,
        new_file_path:Path,
        output_file_path:Path,
        realtime_initial:float,
        output_open_mode:str='xt',
    ) -> dict:
        '''
        Largely a wrapper around vrp_diff_list.  Writes result metadata and diff objects to output_file_path.
        Returns result metadata.
        '''
        logger.info(F'Loading data from {str(old_file_path)} and {str(new_file_path)}')
        # load JSON data from both files
        if old_file_path.suffix == '.bz2':
            old_file = bz2.open(old_file_path)
        else:
            old_file = open(old_file_path)
        old_data = json.load(old_file)
        if new_file_path.suffix == '.bz2':
            new_file = bz2.open(new_file_path)
        else:
            new_file = open(new_file_path)
        new_data = json.load(new_file)
        # open the output file
        if output_file_path.suffix == '.bz2':
            output_file = bz2.open(output_file_path, output_open_mode)
        else:
            output_file = open(output_file_path, output_open_mode)
        # execute vrp_diff_list
        logger.info(F'Diff-ing {len(old_data["roas"])} old and {len(new_data["roas"])} new records...')
        diff_objs = cls.vrp_diff_list(
            old_roas=old_data['roas'],
            new_roas=new_data['roas'],
        )
        # generate metadata
        realtime_delta = time.time() - realtime_initial
        times = os.times()
        result_metadata = {
            'diff_count': len(diff_objs),
            'diff_program': sys.argv[0],
            'hostname': socket.gethostname(),
            'times': {
                'realtime': realtime_delta,
                'user': times.user,
                'system': times.system,
            },
            'timestamp': int(time.time()),
            'user': getpass.getuser(),
            'vrp_cache_old': {
                'filename': old_file_path.name,
                'metadata': old_data['metadata'],
            },
            'vrp_cache_new': {
                'filename': new_file_path.name,
                'metadata': new_data['metadata'],
            },
        }
        try:
            import psutil
            memory_use_rss = psutil.Process().memory_info().rss
            result_metadata['memory_use_rss_mb'] = int(memory_use_rss / 1048576)
        except:
            logger.info(F'Unable to invoke psutil.Process().memory_info() to get RAM use.  Omitting it from metadata.')
            pass
        # write result bz2
        logger.info(F'Writing results to JSON file {str(output_file_path)}')
        output_file.write(
            F'{{\n'
            F'"object_type": "rpkilog_vrp_cache_diff_set",\n'
            F'"metadata": {json.dumps(result_metadata, indent=4, sort_keys=True)},\n'
            F'"vrp_diffs": [\n'
        )
        for idx in range(len(diff_objs)):
            diff_obj = diff_objs[idx]
            if idx < len(diff_objs) - 1:
                separator = ',\n'
            else:
                separator = '\n'
            diff_str = diff_obj.as_json_str()
            output_file.write('    ' + diff_str + separator)
        output_file.write(']\n}\n')
        output_file.close()
        # return result_metadata
        return result_metadata

    @classmethod
    def vrp_diff_list(cls, old_roas:list[dict], new_roas:list[dict]) -> list:
        """
        Given two lists of VRPs, return a list of VrpDiff objects.
        """
        retlist = []
        count_delete = 0
        count_new = 0
        count_replace = 0
        count_unchanged = 0
        initial_count_old = len(old_roas)
        initial_count_new = len(new_roas)
        initial_count_both = initial_count_old + initial_count_new
        progress_log_interval = initial_count_both / 10
        progress_log_next = initial_count_both - progress_log_interval
        # Add one to this for the benefit of the first loop iteration
        input_roa_count = len(old_roas) + len(new_roas) + 1

        # Convert input dicts to Roa objects and sort into deques (popleft() is O(1) vs O(n) for pop(0)).
        old_roa_objs = []
        for roa_dict in old_roas:
            old_roa_objs.append(Roa(**roa_dict))
        old_deque = deque(sorted(old_roa_objs, key=Roa.sortable))
        new_roa_objs = []
        for roa_dict in new_roas:
            new_roa_objs.append(Roa(**roa_dict))
        new_deque = deque(sorted(new_roa_objs, key=Roa.sortable))

        process_time_progress = time.process_time()
        while len(old_deque) + len(new_deque) > 0:
            # Every time through the loop, we must pop one entry from one or both deques.
            # If we don't, we're stuck, and that's a bug.  That's why we check.
            if not len(old_deque) + len(new_deque) < input_roa_count:
                raise Exception('STUCK not making progress consuming input ROAs')
            input_roa_count = len(old_deque) + len(new_deque)
            if input_roa_count < progress_log_next:
                complete_pct = (initial_count_both - input_roa_count) / initial_count_both * 100
                process_time_new = time.process_time()
                process_time_delta = process_time_new - process_time_progress
                process_time_progress = process_time_new
                logger.info(f"Progress {complete_pct:.0f}%  ROAs remaining {input_roa_count} / {initial_count_both}"
                            f" CPU (usr+sys) {process_time_delta:.1f}s")
                progress_log_next -= progress_log_interval
            # If either deque is empty, old_next or new_next will be None.
            old_next = old_deque[0] if len(old_deque) else None
            new_next = new_deque[0] if len(new_deque) else None
            # If first entry in both deques have identical (ta, prefix, maxLength, asn) we'll pop both
            # deques and dispose of both items (will become an UNCHANGED or REPLACE diff).
            #
            # If those entries are different, we'll process whichever one has a lower sort-order.
            # If that's an OLD entry, we'll be emitting a DELETE diff.
            # If it's a NEW entry, we'll be emitting a NEW diff.
            if old_next != None and new_next != None and old_next.primary_key() == new_next.primary_key():
                # UNCHANGED or REPLACE diff, depending on whether expires has been updated
                if old_next == new_next:
                    count_unchanged += 1
                    # No diff-obj is emitted for unchanged ROAs
                else:
                    count_replace += 1
                    logger.debug('REPLACE found: {old_list_next} -> {new_list_next}')
                    diff = VrpDiff(old_roa=old_next, new_roa=new_next)
                    retlist.append(diff)
                old_deque.popleft()
                new_deque.popleft()
                continue
            # Entries have different primary keys.  Process whichever one has a lower sort-order.
            if new_next==None or (old_next!=None and old_next.sortable() < new_next.sortable()):
                count_delete += 1
                logger.debug('DELETE found: {old_list_next}')
                diff = VrpDiff(old_roa=old_next, new_roa=None)
                retlist.append(diff)
                old_deque.popleft()
                continue
            else:
                count_new += 1
                logger.debug('NEW found: {new_list_next}')
                diff = VrpDiff(old_roa=None, new_roa=new_next)
                retlist.append(diff)
                new_deque.popleft()
                continue
        if initial_count_old + initial_count_new == count_unchanged * 2 + count_replace * 2 + count_delete + count_new:
            logger.info('Results add up!')
        else:
            logger.critical(F'initial_count_old: {initial_count_old}')
            logger.critical(F'initial_count_new: {initial_count_new}')
            logger.critical(F'initial_counts:    {initial_count_old + initial_count_new}')
            logger.critical(F'count_delete:      {count_delete}')
            logger.critical(F'count_new:         {count_new}')
            logger.critical(F'count_replace:     {count_replace}')
            logger.critical(F'count_unchanged:   {count_unchanged}')
            logger.critical(F'diff_counts:       {count_unchanged * 2 + count_replace * 2 + count_delete + count_new}')
            logger.critical(F'initial_counts and diff_counts SHOULD BE EQUAL')
            raise SystemExit(1)
        return retlist

    @classmethod
    def es_create_diff_index_for_datetime(cls, index_datetime:datetime, es_client:OpenSearch) -> str:
        '''
        Ensure necessary index exists for vrp diff data created from new vrp cache at given datetime.
        Returns the datetime-appropriate index name, e.g. '198110'.
        '''
        index_name = index_datetime.strftime('diff-%Y%m')
        es_client.indices.create(
            index=index_name,
            body={
                'settings': {
                    'number_of_replicas': 0,
                    'number_of_shards': 3,
                    #'refresh_interval': 60,
                },
                'mappings': {
                    'properties': {
                        'observation_timestamp': {
                            'type': 'date',
                            'format': 'strict_date_time_no_millis'
                        },
                        'verb': { 'type': 'keyword' },
                        'prefix': { 'type': 'ip_range' },
                        'maxLength': { 'type': 'integer' },
                        'asn': { 'type': 'long' },
                        'ta': { 'type': 'keyword' },
                        'old_expires': {
                            'type': 'date',
                            'format': 'strict_date_time_no_millis'
                        },
                        'new_expires': {
                            'type': 'date',
                            'format': 'strict_date_time_no_millis'
                        },
                        'old_roa': { 'type': 'object' },
                        'new_roa': { 'type': 'object' },
                    }
                }
            },
            ignore=400,
        )
        return index_name

    @classmethod
    def get_datetime_from_diff_filename(cls, summary_filename:str, with_timezone:bool=True) -> datetime:
        '''
        Returns a datetime object or raises a ValueError if the filename does not match our regex.
        '''
        rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.vrpdiff\.json(\.bz2)?$', summary_filename)
        if not rem:
            raise ValueError(F'Input file name didnt match our regex: {summary_filename}')
        dt = dateutil.parser.parse(rem.group('datetime'))
        return(dt)

    @classmethod
    def get_diff_filename_from_summary_filename(cls, summary_filename:str, diff_bzip2:bool=True):
        summary_filename = str(summary_filename)
        rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.json(\.bz2)?$', summary_filename)
        if not rem:
            raise ValueError(F'Input file name didnt match our regex: {summary_filename}')
        diff_filename = F'{rem.group("datetime")}.vrpdiff.json'
        if diff_bzip2:
            diff_filename += '.bz2'
        return diff_filename

    @classmethod
    def get_es_client(
        cls,
        es_hostname:str,
        es_port:int=443,
    ):
        '''
        Move this to a utility module?

        FIXME: hard-coded AWS region
        '''
        aws_credentials = boto3.Session().get_credentials()
        try:
            aws_auth = AWS4Auth(
                region='us-east-1',
                service='es',
                refreshable_credentials=aws_credentials
            )
        except:
            aws_auth = AWS4Auth(
                aws_credentials.access_key,
                aws_credentials.secret_key,
                'us-east-1',
                'es',
                aws_credentials.token,
            )
        es_client = OpenSearch(
            hosts = [
                {'host': es_hostname, 'port': es_port},
            ],
            http_auth=aws_auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            http_compress=True,
        )
        return es_client

    @classmethod
    def aws_lambda_entry_point(cls, event, context):
        """
        Accept invocations from S3 or SNS when new RPKI snapshot-summary files are stored in S3.
        
        See below for AWS documentation on the envelope & message structures.  Note, S3 really does use
        "eventSource" while SNS uses "EventSource."  When receiving messages via SNS the S3 events really
        are serialized, so you have to do a json.loads().

        S3 notification: https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html
        SNS envelope: https://docs.aws.amazon.com/lambda/latest/dg/with-sns.html#sns-sample-event
        
        S3:
            {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "s3": {
                            "bucket": {
                                "name": "bucket-name-here"
                            }
                            "object": {
                                "key": "object/key.here"
                            }
                        }
                    }
                ]
            }
 
        SNS:
            {
                "Records": [
                    {
                        "EventSource": "aws:sns",
                        "Sns": {
                            "Message": "json serialized message is here; json.loads() it"
                        }
                    }
                ]
            }
        """
        logger.info(f'rpkilog version {importlib.metadata.version("rpkilog")}')
        dst_bucket_name = os.getenv('diff_bucket')

        s3_records = []

        for outer_record in event['Records']:
            if outer_record.get('EventSource') == 'aws:sns':
                s3_notification = json.loads(outer_record['Sns']['Message'])
                if s3_notification.get('Event') == 's3:TestEvent':
                    logger.info('Skipping S3 test event from bucket %s', s3_notification.get('Bucket', '(unknown)'))
                    continue
                s3_records.extend(s3_notification['Records'])
            else:
                s3_records.append(outer_record)
                
        record_summary = []
        for r in s3_records:
            if r.get('eventSource', '') != 'aws:s3':
                raise ValueError(f'unrecognized invocation event/argument data: {event}')
            record_summary.append({'bucket': r['s3']['bucket']['name'], 'key': r['s3']['object']['key']})
        logger.info(json.dumps({'s3_record_count': len(s3_records), 's3_records': record_summary}))
        if len(s3_records) > 1:
            logger.warning(f'Received {len(s3_records)} S3 notification records in one invocation; processing all.')

        retval = []
        for s3_record in s3_records:
            src_bucket_name = s3_record['s3']['bucket']['name']
            new_file_key = s3_record['s3']['object']['key']
            result = cls.generic_entry_point(
                src_bucket_name=src_bucket_name,
                new_file_key=new_file_key,
                diff_bucket_name=dst_bucket_name,
            )
            retval.append(result)
        return retval

    @classmethod
    def aws_lambda_entry_point_import(cls, event, context):
        """
        Accept invocations from S3 (S3->Lambda), SNS (S3->SNS->Lambda), or SQS
        (S3->SNS->SQS->Lambda) when new VRP diff files are stored in S3.

        The direct S3->Lambda path delivers S3 event records directly.  The S3->SNS->Lambda path
        wraps each S3 event in an SNS notification ('EventSource' == 'aws:sns'), whose Message is the
        serialized S3 event.  The S3->SNS->SQS->Lambda path wraps that SNS notification in an SQS
        record ('eventSource' == 'aws:sqs'), so the S3 event must be unwrapped twice
        (SQS body -> SNS Message -> S3 Records).

        S3 notification: https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html
        SNS envelope: https://docs.aws.amazon.com/lambda/latest/dg/with-sns.html#sns-sample-event
        SQS event: https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html

        S3:
            {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "s3": {"bucket": {"name": "..."}, "object": {"key": "..."}}
                    }
                ]
            }

        SNS (Sns.Message is a serialized S3 event):
            {
                "Records": [
                    {
                        "EventSource": "aws:sns",
                        "Sns": {"Message": "<serialized S3 event>"}
                    }
                ]
            }

        SQS (body is an SNS notification whose Message is a serialized S3 event):
            {
                "Records": [
                    {
                        "eventSource": "aws:sqs",
                        "body": "{\\"Type\\": \\"Notification\\", \\"Message\\": \\"<serialized S3 event>\\"}"
                    }
                ]
            }
        """
        logger.info(f'rpkilog version {importlib.metadata.version("rpkilog")}')
        es_bulk_batch_size = int(os.getenv('es_bulk_batch_size', 200))
        es_endpoint = os.getenv('es_endpoint')
        if not es_endpoint:
            raise RuntimeError('missing es_endpoint environment variable')

        s3_records = []
        for outer_record in event['Records']:
            if outer_record.get('eventSource') == 'aws:sqs':
                sqs_body = json.loads(outer_record['body'])
                # When fed by S3->SNS->SQS, the SQS body is an SNS notification envelope whose
                # Message is the serialized S3 event.  Otherwise treat the body as the S3 event.
                if sqs_body.get('Type') == 'Notification':
                    s3_notification = json.loads(sqs_body['Message'])
                else:
                    s3_notification = sqs_body
            elif outer_record.get('EventSource') == 'aws:sns':
                # S3 really does use lowercase "eventSource" while SNS uses "EventSource".
                s3_notification = json.loads(outer_record['Sns']['Message'])
            else:
                s3_records.append(outer_record)
                continue
            if s3_notification.get('Event') == 's3:TestEvent':
                logger.info('Skipping S3 test event from bucket %s', s3_notification.get('Bucket', '(unknown)'))
                continue
            s3_records.extend(s3_notification['Records'])

        record_summary = []
        for r in s3_records:
            if r.get('eventSource', '') != 'aws:s3':
                raise ValueError(f'unrecognized invocation event/argument data: {event}')
            record_summary.append({'bucket': r['s3']['bucket']['name'], 'key': r['s3']['object']['key']})
        logger.info(json.dumps({'s3_record_count': len(s3_records), 's3_records': record_summary}))
        if len(s3_records) > 1:
            logger.warning(f'Received {len(s3_records)} S3 notification records in one invocation; processing all.')

        retval = []
        for s3_record in s3_records:
            src_s3_bucket_name = s3_record['s3']['bucket']['name']
            src_s3_key = s3_record['s3']['object']['key']
            result = cls.generic_entry_point_import(
                es_bulk_batch_size=es_bulk_batch_size,
                es_endpoint=es_endpoint,
                src_s3_bucket_name=src_s3_bucket_name,
                src_s3_key=src_s3_key,
            )
            retval.append(result)
        logger.info(retval)
        return retval

    @classmethod
    def cli_entry_point(cls):
        ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
        ag1 = ap.add_argument_group('Use S3 for I/O to simulate AWS Lambda workflow')
        ag1.add_argument('--summary-bucket', help='S3 bucket containing VRP cache summaries')
        ag1.add_argument('--diff-bucket', help='Destination S3 bucket for VRP cache diff output')
        ag1.add_argument('--summary-cache', default=None, type=Path, help='Path to summary cache directory on local filesystem')
        ag1.add_argument('--new-file-key', help='S3 key of "new" file key to use for generating a diff')
        ag1.add_argument('--reprocess-all-s3-summary-files', action='store_true', help='Invoke diff process on all summary files')
        ag1.add_argument('--invoke-lambda-on-all-s3-summary-files', type=str, help='Invoke given lambda (asynchronously) on all summary files')
        ag1.add_argument('--reprocess-max-files', type=int, help='Stop reprocessing after first N files')
        ag1.add_argument('--diff-collision-behavior', default='overwrite', choices=['error', 'overwrite', 'retain'],
                         help='If "error", exit with an error upon collision.  If "overwrite", overwrite'
                              ' if a pre-existing diff is found.  If "retain", calculate new diff but'
                              ' do not upload it; retain the old file.')
        ag2 = ap.add_argument_group('Use local files')
        ag2.add_argument('--old-file', type=Path, help='Path to the "old" file used for diffing')
        ag2.add_argument('--new-file', type=Path, help='Path to the "new" file')
        ag2.add_argument('--output-file', type=Path, help='Output file')
        ag3 = ap.add_argument_group('Debug options')
        ag3.add_argument('--debugger', default=False, action='store_true', help='If specified, invoke pdb.set_break()')
        ag3.add_argument('--log-level', type=str, help='Log level.  Try CRITICAL, ERROR, INFO (default) or DEBUG.')
        args = vars(ap.parse_args())
        logging.basicConfig(
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
        logger.setLevel(args.get('log_level', 'INFO'))
        logger.info(f'rpkilog version {importlib.metadata.version("rpkilog")}')
        if args['debugger']:
            import pdb
            pdb.set_trace()

        diff_collision_behavior = CollisionBehavior.OVERWRITE
        match args.get('diff_collision_behavior', 'overwrite'):
            case 'overwrite':
                diff_collision_behavior = CollisionBehavior.OVERWRITE
            case 'retain':
                diff_collision_behavior = CollisionBehavior.RETAIN
            case 'error':
                diff_collision_behavior = KeyError('Collision: diff output file already exists in diff'
                                                   ' bucket, and desired --diff-collision-behavior is error')
            case _:
                raise ValueError(f'Unexpected diff_collision_behavior value: {args["diff_collision_behavior"]!r}')

        if 'new_file_key' in args:
            metadata = cls.generic_entry_point(
                src_bucket_name=args['summary_bucket'],
                new_file_key=args['new_file_key'],
                diff_bucket_name=args['diff_bucket'],
                diff_collision_behavior=diff_collision_behavior,
                summary_cache=args['summary_cache'],
            )
            print(json.dumps(metadata, indent=4, sort_keys=True))
        elif 'old_file' in args:
            metadata = cls.vrp_diff_from_files(
                old_file_path=args['old_file'],
                new_file_path=args['new_file'],
                output_file_path=args['output_file'],
                realtime_initial=time.time(),
            )
            print(json.dumps(metadata, indent=4, sort_keys=True))
        elif 'reprocess_all_s3_summary_files' in args:
            # Get a list of all the VRP cache diff summary files in S3 and invoke vrp_diff_from_files()
            # on every one of those.  This is used for re-building all diffs from our summary archive.
            files_processed = 0
            diff_bucket = boto3.resource('s3').Bucket(args['diff_bucket'])
            summary_bucket = boto3.resource('s3').Bucket(args['summary_bucket'])
            for buckobj in summary_bucket.objects.all():
                rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.json(\.bz2)?$', buckobj.key)
                if not rem:
                    logger.info(F'Skipping S3 key {buckobj.key} which does not match our regex')
                    continue
                if args.get('invoke_lambda_on_all_s3_summary_files', False):
                    logger.info(F'INVOKING_LAMBDA on {buckobj.key}')
                    invoke_payload = {
                        'Records': [
                            {
                                's3': {
                                    'bucket': {
                                        'name': str(args['summary_bucket'])
                                    },
                                    'object': {
                                        'key': str(buckobj.key)
                                    }
                                }
                            }
                        ]
                    }
                    invoke_result = boto3.client('lambda').invoke(
                        FunctionName=args['invoke_lambda_on_all_s3_summary_files'],
                        InvocationType='Event',
                        Payload=json.dumps(invoke_payload),
                    )
                    logger.info(F'LAMBDA_ASYNC_INVOKE_RESULT StatusCode {invoke_result["StatusCode"]} payload: {invoke_result["Payload"].read()}')
                else:
                    logger.info(F'Invoking generic_entry_point() for summary key {buckobj.key}...')
                    metadata = cls.generic_entry_point(
                        src_bucket_name=args['summary_bucket'],
                        new_file_key=buckobj.key,
                        diff_bucket_name=args['diff_bucket'],
                        diff_collision_behavior=diff_collision_behavior,
                        summary_cache=args['summary_cache'],
                    )
                    print(json.dumps(metadata, indent=4, sort_keys=True))
                files_processed += 1
                logger.info(F'Completed processing summary number {files_processed} key {buckobj.key}')
                if args.get('reprocess_max_files', 1000000000) <= files_processed:
                    logger.info(F'Reprocessed max number of files per CLI.  Job complete.')
                    break
        else:
            raise KeyError('Command line arguments missing')

    @classmethod
    def cli_entry_point_import(cls):
        invocation_time=time.time()
        ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
        ap.add_argument('--bucket', help='S3 bucket containing diff file')
        ap.add_argument('--key', type=Path, help='S3 key of diff file')
        ap.add_argument('--all-files', action='store_true',
            help='Import all diff files found in the S3 bucket.  Used to re-populate database after a wipe.  Youngest files first.'
        )
        ap.add_argument('--all-limit', type=int, help='Max number of files to import when using -all-files')
        ap.add_argument('--all-date-min', type=dateutil.parser.parse, help='Import files only on-or-after this date')
        ap.add_argument('--all-date-max', type=dateutil.parser.parse, help='Import files only on-or-before this date')
        ap.add_argument('--bulk-batch-size', type=int, default=200, help='Number of records inserted per ES _bulk operation')
        ap.add_argument('--es-endpoint', help='ElasticSearch endpoint')
        ap.add_argument('--limit-cpu', type=int, help='Try to limit CPU utilization to N percent, e.g. 10.')
        ap.add_argument('--log-level', help='Log level.  Try ERROR, INFO (default) or DEBUG.')
        ap.add_argument('--debugger', action='store_true', help='Initiate debugger upon startup')
        args = vars(ap.parse_args())
        logging.basicConfig(
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
        if 'debugger' in args:
            import pdb
            pdb.set_trace()
        logger.setLevel(args.get('log_level', 'INFO'))
        logger.info(f'rpkilog version {importlib.metadata.version("rpkilog")}')
        for argname in ['all_date_min', 'all_date_max']:
            if argname in args:
                # Add time zone information to the argument
                args[argname] = args[argname].replace(tzinfo=timezone.utc)

        if args.get('all_files', False):
            # List files in the S3 bucket.
            # Invoke cls.generic_entry_point_import() on every one, youngest first (reverse sort order).
            diff_bucket = boto3.resource('s3').Bucket(args['bucket'])
            import_file_count = 0
            diff_bucket_objects = sorted(diff_bucket.objects.all(), key=operator.attrgetter('key'), reverse=True)
            for buckobj in diff_bucket_objects:
                dt = cls.get_datetime_from_diff_filename(summary_filename=buckobj.key)
                if 'all_date_min' in args:
                    if dt < args['all_date_min']:
                        logger.debug(F'SKIP file {buckobj.key} because it is earlier than --all-date-min argument')
                        continue
                if 'all_date_max' in args:
                    if args['all_date_max'] < dt:
                        logger.debug(F'SKIP file {buckobj.key} because it is later than --all-date-max argument')
                        continue
                logger.info(F'Importing {buckobj.key}')
                result = cls.generic_entry_point_import(
                    es_bulk_batch_size=args['bulk_batch_size'],
                    es_endpoint=args['es_endpoint'],
                    progress_bar_enable=True,
                    src_s3_bucket_name=args['bucket'],
                    src_s3_key=buckobj.key,
                )
                import_file_count += 1
                logger.info(F'Imported file count {import_file_count} name {buckobj.key} result: {json.dumps(result)}')
                if args.get('all_limit', 1000000000) <= import_file_count:
                    # reached --all-limit max file count
                    break
                if 'limit_cpu' in args:
                    cls.limit_cpu_sleep(invocation_time=invocation_time, limit=args['limit_cpu']/100)
        else:
            result = cls.generic_entry_point_import(
                es_bulk_batch_size=args['bulk_batch_size'],
                es_endpoint=args['es_endpoint'],
                src_s3_bucket_name=args['bucket'],
                src_s3_key=args['key']
            )
            print(json.dumps(result))

    @classmethod
    def cli_entry_point_diff_import_from_sqs(cls):
        """
        Drain an SQS queue of rpkilog-diff object-created notifications and import each diff
        file into OpenSearch.

        The primary use case is populating a dev OpenSearch instance from the diff_dev queue.
        Messages are deleted from the queue only after a successful import.  Use --dry-run to
        validate SQS and S3 access without touching OpenSearch or acknowledging messages.

        Handles both the direct S3 event format and the S3->SNS->SQS envelope format.
        """
        ap = argparse.ArgumentParser(
            description='Import VRP diff files from an SQS queue into OpenSearch.',
            argument_default=argparse.SUPPRESS,
        )
        ap.add_argument('--sqs-name', required=True,
                        help='SQS queue name to consume (e.g. diff_dev)')
        ap.add_argument('--bucket', required=True,
                        help='S3 bucket containing diff files (e.g. rpkilog-diff)')
        ap.add_argument('--bulk-batch-size', type=int, default=200,
                        help='Number of records per OpenSearch _bulk operation (default: 200)')
        ap.add_argument('--es-endpoint',
                        help='OpenSearch endpoint hostname (required unless --dry-run)')
        ap.add_argument('--max-message-count', type=int,
                        help='Stop after processing this many SQS messages')
        ap.add_argument('--dry-run', action='store_true', default=False,
                        help='Read from SQS and S3 but skip OpenSearch inserts and SQS deletes')
        ap.add_argument('--log-level', help='Log level.  Try ERROR, INFO (default) or DEBUG.')
        ap.add_argument('--debugger', action='store_true', help='Initiate debugger upon startup')
        args = vars(ap.parse_args())
        logging.basicConfig(
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
        if 'debugger' in args:
            import pdb
            pdb.set_trace()
        logger.setLevel(args.get('log_level', 'INFO'))
        logger.info(f'rpkilog version {importlib.metadata.version("rpkilog")}')
        if not args['dry_run'] and 'es_endpoint' not in args:
            ap.error('--es-endpoint is required unless --dry-run is set')
        if args['dry_run']:
            logger.info('Dry-run mode: SQS messages will not be deleted; OpenSearch will not be written')

        sqs = boto3.client('sqs')
        queue_url = sqs.get_queue_url(QueueName=args['sqs_name'])['QueueUrl']

        messages_processed = 0
        keys_imported = 0
        max_message_count = args.get('max_message_count', None)

        for message in receive_all_messages(sqs, queue_url):
            if max_message_count is not None and messages_processed >= max_message_count:
                break
            message_succeeded = True
            for _bucket, key, _record in s3_events_from_message(message):
                logger.info('Importing key %s from bucket %s', key, args['bucket'])
                result = cls.generic_entry_point_import(
                    es_bulk_batch_size=args['bulk_batch_size'],
                    es_endpoint=args['es_endpoint'],
                    src_s3_bucket_name=args['bucket'],
                    src_s3_key=key,
                    dry_run=args['dry_run'],
                )
                logger.info('Result for key %s: %s', key, json.dumps(result))
                keys_imported += 1
            if not args['dry_run'] and message_succeeded:
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message['ReceiptHandle'])
            messages_processed += 1

        logger.info('Done: %d message(s) processed, %d key(s) imported', messages_processed, keys_imported)

    @classmethod
    def generic_entry_point(
        cls,
        src_bucket_name:str,
        new_file_key:str,
        diff_bucket_name:str,
        diff_collision_behavior: Exception | CollisionBehavior = CollisionBehavior.OVERWRITE,
        summary_cache:Path=None,
        tmp_dir:Path=None,
    ):
        '''
        Invoke by cli_entry_point or aws_lambda_entry_point.
        '''
        realtime_initial = time.time()
        logger.info(F'Invoked for new_file_key={new_file_key}')
        s3 = boto3.client('s3')
        if tmp_dir==None:
            tmp_dir = Path('/tmp')

        rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.json(\.bz2)?$', new_file_key)
        if not rem:
            raise ValueError(F'Input file name didnt match our regex: {new_file_key}')
        new_file_datestr = rem.group('datetime')
        new_file_datetime = dateutil.parser.parse(rem.group('datetime'))
        output_file_key=F'{new_file_datestr}.vrpdiff.json.bz2'
        output_file_path=Path(tmp_dir, output_file_key)
        collision = False
        if diff_collision_behavior is not CollisionBehavior.OVERWRITE:
            try:
                s3.head_object(Bucket=diff_bucket_name, Key=output_file_key)
                collision = True
            except ClientError as exc:
                if exc.response['Error']['Code'] not in ('404', 'NoSuchKey'):
                    raise
            if collision:
                if isinstance(diff_collision_behavior, Exception):
                    raise diff_collision_behavior
                logger.info(
                    F'Collision: {output_file_key} already exists in {diff_bucket_name}; '
                    F'diff will be generated but not uploaded (diff_collision_behavior={diff_collision_behavior})'
                )
        src_bucket = boto3.resource('s3').Bucket(src_bucket_name)
        try:
            old_file_key = list_s3_object_previous(bucket=src_bucket, subject_datetime=new_file_datetime)
        except KeyError:
            logger.warning(f'No file found in {src_bucket_name} older than {new_file_datetime}. Cannot produce diff.')
            return

        if summary_cache:
            new_file_path = Path(summary_cache, new_file_key)
            old_file_path = Path(summary_cache, old_file_key)
        else:
            new_file_path = Path(tmp_dir, new_file_key)
            old_file_path = Path(tmp_dir, old_file_key)
        if summary_cache and old_file_path.exists():
            logger.info(F'Using cache to access {old_file_key}')
        else:
            logger.info(F'Downloading {old_file_key} from S3')
            s3.download_file(Bucket=src_bucket_name, Key=old_file_key, Filename=str(old_file_path))
        if summary_cache and new_file_path.exists():
            logger.info(F'Using cache to access {new_file_key}')
        else:
            logger.info(F'Downloading {new_file_key} from S3')
            s3.download_file(Bucket=src_bucket_name, Key=new_file_key, Filename=str(new_file_path))

        metadata = cls.vrp_diff_from_files(
            old_file_path=old_file_path,
            new_file_path=new_file_path,
            output_file_path=output_file_path,
            realtime_initial=realtime_initial,
        )
        if collision:
            logger.info(F'Skipping upload of {output_file_key}: collision with pre-existing object in {diff_bucket_name}')
        else:
            logger.info(F'Uploading vrp diff {output_file_key} to S3, replacing existing object of same key')
            s3.upload_file(
                Filename=str(output_file_path),
                Bucket=diff_bucket_name,
                Key=output_file_key,
            )
        if summary_cache==None:
            os.remove(old_file_path)
            os.remove(new_file_path)
        os.remove(output_file_path)
        return metadata

    @classmethod
    def generic_entry_point_import(
        cls,
        es_endpoint:str,
        src_s3_bucket_name:str,
        src_s3_key:str,
        es_bulk_batch_size:int=200,
        progress_bar_enable:bool=False,
        dry_run:bool=False,
    ):
        """
        Invoked by cli_entry_point_import or aws_lambda_entry_point_import

        Retrieve given vrp diff file from S3 and insert its records into ElasticSearch.
        When dry_run=True, S3 download and file parsing are performed but no OpenSearch calls
        are made and no index is created.  Returns 'records_would_insert' instead of
        'records_inserted' to make dry-run results distinguishable.
        """
        logging.basicConfig(
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
        logging.getLogger('opensearch').setLevel(logging.INFO)
        realtime_initial = time.time()
        src_s3_path = Path(src_s3_key)
        if not '.json' in src_s3_path.suffixes:
            raise ValueError(F'Invoked upon upload of a file without .json in its Path().suffixes: {src_s3_path}')
        s3 = boto3.client('s3')
        tmpdir = tempfile.TemporaryDirectory()
        diff_file_path = Path(tmpdir.name, src_s3_path.name)
        rem = re.match(r'^(?P<datetime>\d{8}T\d{6}Z)', diff_file_path.name)
        diff_datetime = dateutil.parser.parse(rem.group('datetime'))
        if not dry_run:
            es_client = cls.get_es_client(es_hostname=es_endpoint)
            es_index = cls.es_create_diff_index_for_datetime(index_datetime=diff_datetime, es_client=es_client)
        s3.download_file(Bucket=src_s3_bucket_name, Key=str(src_s3_key), Filename=str(diff_file_path))
        if diff_file_path.suffix == '.bz2':
            diff_file = bz2.open(diff_file_path)
        elif diff_file_path.suffix == '.json':
            diff_file = open(diff_file_path)
        else:
            raise ValueError(F'Invoked upon a file with a Path().suffix I cannot open: {diff_file_path}')
        diff_data = json.load(diff_file)
        logger.info(f'diff contains {len(diff_data["vrp_diffs"])} records')
        records_count = 0
        if dry_run:
            records_count = len(diff_data['vrp_diffs'])
        elif es_bulk_batch_size > 1:
            #BEGIN bulk insert records
            progress_bar = tqdm(total=len(diff_data["vrp_diffs"]), unit="records", disable=not progress_bar_enable)
            for batch_base_index in range(0, len(diff_data['vrp_diffs']), es_bulk_batch_size):
                bulk_actions = []
                if batch_base_index + es_bulk_batch_size <= len(diff_data['vrp_diffs']):
                    batch_max_index = batch_base_index + es_bulk_batch_size
                else:
                    batch_max_index = len(diff_data['vrp_diffs'])
                for vrpd_index in range(batch_base_index, batch_max_index):
                    vrpd_record = diff_data['vrp_diffs'][vrpd_index]
                    vrpd_obj = VrpDiff.from_json_obj(vrpd_record)
                    insertable = vrpd_obj.es_bulk_insertable_dict(
                        diff_datetime=diff_datetime,
                        es_index=es_index,
                    )
                    bulk_actions.append(insertable)
                # https://elasticsearch-py.readthedocs.io/en/7.x/helpers.html#elasticsearch.helpers.streaming_bulk
                bulk_generator = opensearchpy.helpers.streaming_bulk(
                    client=es_client,
                    actions=bulk_actions,
                    initial_backoff=5,
                    max_backoff=20,
                    max_retries=5,
                )
                records_inserted_this_batch = 0
                for ok, bulk_action_result in bulk_generator:
                    if ok:
                        records_inserted_this_batch += 1
                        records_count += 1
                    else:
                        raise ValueError(F'bulk insert returned an unsuccessful result: {bulk_action_result}')
                progress_bar.update(records_inserted_this_batch)
            progress_bar.close()
            #DONE bulk insert records
        else:
            for vrp_diff_record in diff_data['vrp_diffs']:
                vrp_diff_obj = VrpDiff.from_json_obj(vrp_diff_record)
                vrp_diff_obj.es_insert(
                    diff_datetime=diff_datetime,
                    es_client=es_client,
                    es_index=es_index,
                )
                records_count += 1
        runtime = time.time() - realtime_initial
        count_key = 'records_would_insert' if dry_run else 'records_inserted'
        retdict = {
            count_key: records_count,
            'runtime': runtime,
            'src_s3_bucket_name': src_s3_bucket_name,
            'src_s3_key': src_s3_key,
        }
        return retdict

def aws_lambda_entry_point(event, context):
    retval = VrpDiff.aws_lambda_entry_point(event, context)
    return retval

def aws_lambda_entry_point_import(event, context):
    retval = VrpDiff.aws_lambda_entry_point_import(event, context)
    return retval
