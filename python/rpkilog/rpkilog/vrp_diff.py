#!/usr/bin/env python
import argparse
import bz2
import getpass
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
import dateutil.parser
import netaddr
import opensearchpy.helpers
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from tqdm import tqdm

logger = logging.getLogger(__name__)

class Roa():
    def __init__(
        self,
        asn:int,
        prefix:netaddr.IPNetwork,
        maxLength:int,
        ta:str,
        expires:int=0,
        source_host:str=None,
        source_time:datetime=None,
    ):
        if isinstance(asn, str) and asn.startswith('AS'):
            # tolerate old VRP Cache files with asn="AS64496" instead of asn=64496
            rem = re.match(r'^AS(?P<asn>\d+)$', asn)
            if not rem:
                raise ValueError(F'Cannot get integer ASN from asn argument passed as string: {asn}')
            asn = int(rem.group(asn))
        if asn < 0 or asn > 2**32-1:
            raise ValueError(F'Invalid asn F{asn}')
        self.asn = int(asn)
        if not isinstance(prefix, netaddr.IPNetwork):
            prefix=netaddr.IPNetwork(prefix)
        self.prefix = prefix
        if maxLength < prefix.prefixlen:
            raise ValueError(F'Invalid maxLength {maxLength} for prefix {prefix}')
        if self.prefix.version == 4 and maxLength > 32:
            raise ValueError(F'Invalid maxLength {maxLength} for prefix {prefix}')
        if self.prefix.version == 6 and maxLength > 128:
            raise ValueError(F'Invalid maxLength {maxLength} for prefix {prefix}')
        self.maxLength = maxLength
        if not isinstance(ta, str):
            raise TypeError(F'Expecting ta to be a str but got a {type(ta)}: {ta}')
        self.ta = ta
        if expires < 0:
            raise ValueError(F'Invalid expires {expires}')
        self.expires = expires
        if source_host!=None:
            self.source_host = source_host
        if source_time!=None:
            self.source_time = source_time

    def __eq__(self, other):
        if not isinstance(other, Roa):
            return NotImplemented
        retval = self.sortable() == other.sortable()
        return retval

    def as_json_obj(self):
        '''
        Return a dict which the default json serializer can consume.

        >>> import json
        >>> roa = Roa(asn=64496, prefix='192.0.2.0/24', maxLength=24, ta='test', expires='372920400')
        >>> jd = roa.as_jdict()
        >>> json.dumps(jd, sort_keys=True)
        '''
        retval = {}
        retval['asn'] = self.asn
        retval['expires'] = self.expires
        retval['maxLength'] = self.maxLength
        retval['prefix'] = str(self.prefix.cidr)
        retval['ta'] = self.ta
        return retval

    def as_json_str(self):
        '''
        Return a serialized JSON string representing the contents of the Roa object-instance.
        '''
        retstr = (
            F'{{'
            F' "prefix": "{str(self.prefix.cidr)}",'
            F' "maxLength": {self.maxLength},'
            F' "asn": {self.asn},'
            F' "expires": {self.expires},'
            F' "ta": "{self.ta}"'
            F' }}'
        )
        return retstr

    def primary_key(self):
        '''
        Return a tuple which can be used to compare ROAs and determine if they are for the same
        prefix, maxLength, asn, and ta.  For example:

        >>> roa1 = Roa(asn=64496, prefix='192.0.2.0/24', maxLength=24, ta='test', expires='372920400')
        >>> roa2 = Roa(asn=64496, prefix='192.0.2.0/24', maxLength=24, ta='test', expires='1000000000')
        >>> roa1.primary_key() == roa2.primary_key()
        True
        >>> roa1.primary_key()
        ('192.0.2.0/24', 24, 64496, 'test')
        '''
        retval = tuple([
            self.prefix.cidr,
            self.maxLength,
            self.asn,
            self.ta
        ])
        return retval

    def sortable(self):
        '''
        Return a containing: netaddr.IPNetwork(prefix).sort_key(), maxLength, asn, ta, expires.
        This is usable by sorted() and our comparison methods __eq__, __lt__, __le__, __ge__, __gt__.
        '''
        rettu = self.prefix.sort_key() + tuple([self.maxLength, self.asn, self.ta, self.expires])
        return rettu

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
    def vrp_diff_list(cls, old_roas:list, new_roas:list) -> list:
        '''
        Given two lists of VRPs, return a list of VrpDiff objects.
        EMPTIES THE INPUT LISTS as a side-effect.  Pass copies if you don't want that!

        SCALE: This could return a generator which reads the input files (or lists) sequentially and
        generates results as-needed.  It would be possible to scale up to a much larger VRP Cache
        without using much RAM.  However, we need to sort the input, because in the real world, input
        VRP cache files had a different (or inconsistent?) sort order in cases when a prefix had multiple
        ROAs with different prefix-lengths.  That would complicate the generator a little.
        '''
        retlist = []
        count_delete = 0
        count_new = 0
        count_replace = 0
        count_unchanged = 0
        initial_count_old = len(old_roas)
        initial_count_new = len(new_roas)
        # Add one to this for the benefit of the first loop iteration
        input_roa_count = len(old_roas) + len(new_roas) + 1
        # Convert the input lists, which are dicts, to Roa objects.
        for idx, roa_dict in enumerate(old_roas):
            old_roas[idx] = Roa(**roa_dict)
        for idx, roa_dict in enumerate(new_roas):
            new_roas[idx] = Roa(**roa_dict)
        # Sort the input lists
        old_roas = sorted(old_roas, key=Roa.sortable)
        new_roas = sorted(new_roas, key=Roa.sortable)

        while len(old_roas) + len(new_roas) > 0:
            # Every time through the loop, we must pop one entry from one or both input lists.
            # If we don't, we're stuck, and that's a bug.  That's why we check.
            if not len(old_roas) + len(new_roas) < input_roa_count:
                raise Exception('STUCK not making progress consuming input ROAs')
            input_roa_count = len(old_roas) + len(new_roas)
            # If either old_roas or new_roas is empty, old_next or new_next will be None.
            old_next = old_roas[0] if len(old_roas) else None
            new_next = new_roas[0] if len(new_roas) else None
            # If first entry in both lists have identical (ta, prefix, maxLength, asn) we'll pop both
            # lists and dispose of both items (will become an UNCHANGED or REPLACE diff).
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
                old_roas.pop(0)
                new_roas.pop(0)
                continue
            # Entries have different primary keys.  Process whichever one has a lower sort-order.
            if new_next==None or (old_next!=None and old_next.sortable() < new_next.sortable()):
                count_delete += 1
                logger.debug('DELETE found: {old_list_next}')
                diff = VrpDiff(old_roa=old_next, new_roa=None)
                retlist.append(diff)
                old_roas.pop(0)
                continue
            else:
                count_new += 1
                logger.debug('NEW found: {new_list_next}')
                diff = VrpDiff(old_roa=None, new_roa=new_next)
                retlist.append(diff)
                new_roas.pop(0)
                continue
        if initial_count_old + initial_count_new == count_unchanged * 2 + count_replace * 2 + count_delete + count_new:
            logger.info('Results add up!')
        else:
            logger.warn(F'initial_count_old: {initial_count_old}')
            logger.warn(F'initial_count_new: {initial_count_new}')
            logger.warn(F'initial_counts:    {initial_count_old + initial_count_new}')
            logger.warn(F'count_delete:      {count_delete}')
            logger.warn(F'count_new:         {count_new}')
            logger.warn(F'count_replace:     {count_replace}')
            logger.warn(F'count_unchanged:   {count_unchanged}')
            logger.warn(F'diff_counts:       {count_unchanged * 2 + count_replace * 2 + count_delete + count_new}')
            logger.warn(F'initial_counts and diff_counts SHOULD BE EQUAL')
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
    def get_old_file_key_from_s3(cls, src_bucket_name:str, new_file_datetime:datetime) -> str:
        '''
        Given a new_file_datetime, list objects in the src_bucket and return key name of the previous
        file by datetime.

        This is used to find which file should be the old_file in our diff process.  It's just a helper
        function for readability.
        '''
        # list all files in src_bucket to determine old_file_key
        src_bucket = boto3.resource('s3').Bucket(src_bucket_name)
        summaries = set()
        for buckobj in src_bucket.objects.all():
            summaries.add(buckobj.key)
        if len(summaries) == 1:
            logger.warning(F'ONLY ONE FILE IN src_bucket {src_bucket_name}.  Is this first ever invocation?')
            return
        # find the filename immediately before the one which invoked us
        for candidate_filename in sorted(summaries, reverse=True):
            rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.json(\.bz2)?$', candidate_filename)
            if not rem:
                logger.warning(F'{src_bucket_name} contained a file not matching our regex: {candidate_filename}')
                continue
            candidate_datetime = dateutil.parser.parse(rem.group('datetime'))
            if candidate_datetime < new_file_datetime:
                # We reverse-sorted the list of files, so the first one with an earlier datetime should be right
                old_file_key = candidate_filename
                return(old_file_key)
        else:
            # no files found which are older than new_file_datetime
            logger.warning(
                F'{src_bucket_name} doesnt contain any files older than {new_file_datetime}'
                F' Is this first ever invocation?'
            )
            return

    @classmethod
    def aws_lambda_entry_point(cls, event, context):
        dst_bucket_name = os.getenv('diff_bucket')
        src_bucket_name = event['Records'][0]['s3']['bucket']['name']
        new_file_key = event['Records'][0]['s3']['object']['key']
        metadata = cls.generic_entry_point(
            src_bucket_name=src_bucket_name,
            new_file_key=new_file_key,
            diff_bucket_name=dst_bucket_name,
        )
        return metadata

    @classmethod
    def aws_lambda_entry_point_import(cls, event, context):
        es_bulk_batch_size = int(os.getenv('es_bulk_batch_size', 200))
        es_endpoint = os.getenv('es_endpoint')
        src_s3_bucket_name = event['Records'][0]['s3']['bucket']['name']
        src_s3_key = event['Records'][0]['s3']['object']['key']
        result = cls.generic_entry_point_import(
            es_bulk_batch_size=es_bulk_batch_size,
            es_endpoint=es_endpoint,
            src_s3_bucket_name=src_s3_bucket_name,
            src_s3_key=src_s3_key,
        )
        return result

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
        ag1.add_argument('--reprocess-skip-existing-diffs', action='store_true', help='Do not reprocess files that would overwrite existing diffs')
        ag2 = ap.add_argument_group('Use local files')
        ag2.add_argument('--old-file', type=Path, help='Path to the "old" file used for diffing')
        ag2.add_argument('--new-file', type=Path, help='Path to the "new" file')
        ag2.add_argument('--output-file', type=Path, help='Output file')
        ag3 = ap.add_argument_group('Debug options')
        ag3.add_argument('--debugger', default=False, action='store_true', help='If specified, invoke pdb.set_break()')
        ag3.add_argument('--log-level', type=str, help='Log level.  Try CRITICAL, ERROR, INFO (default) or DEBUG.')
        args = vars(ap.parse_args())
        logger.setLevel(args.get('log_level', 'INFO'))
        if args['debugger']:
            import pdb
            pdb.set_trace()

        if 'new_file_key' in args:
            metadata = cls.generic_entry_point(
                src_bucket_name=args['summary_bucket'],
                new_file_key=args['new_file_key'],
                diff_bucket_name=args['diff_bucket'],
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
                if args.get('reprocess_skip_existing_diffs', False):
                    diff_filename = cls.get_diff_filename_from_summary_filename(summary_filename=buckobj.key)
                    # If a diff file already exists for this summary, skip this invocation
                    try:
                        diff_bucket.Object(key=diff_filename).load()
                        logger.info(F'SKIPPING_LAMBDA on {buckobj.key} because {diff_filename} already exists')
                        continue
                    except:
                        # Exception indicates the file was not found in S3.
                        pass
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
        if 'debugger' in args:
            import pdb
            pdb.set_trace()
        logger.setLevel(args.get('log_level', 'INFO'))
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
    def generic_entry_point(
        cls,
        src_bucket_name:str,
        new_file_key:str,
        diff_bucket_name:str,
        summary_cache:Path=None,
        tmp_dir:Path=None,
    ):
        '''
        Invoke by cli_entry_point or aws_lambda_entry_point.
        '''
        logging.basicConfig(
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
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
        old_file_key = cls.get_old_file_key_from_s3(
            src_bucket_name=src_bucket_name,
            new_file_datetime=new_file_datetime,
        )
        if old_file_key==None:
            # If no old_file_key was found, we cannot produce a diff.
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
        logger.info(F'Uploading vrp diff {output_file_key} to S3')
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
        es_bulk_batch_size:int=None,
        progress_bar_enable:bool=False,
    ):
        '''
        Invoked by cli_entry_point_import or aws_lambda_entry_point_import

        Retrieve given vrp diff file from S3 and insert its records into ElasticSearch
        '''
        logging.basicConfig(
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
        logging.getLogger('opensearch').setLevel(logging.WARNING)
        if es_bulk_batch_size==None:
            es_bulk_batch_size = 200
        realtime_initial = time.time()
        src_s3_path = Path(src_s3_key)
        if not '.json' in src_s3_path.suffixes:
            raise ValueError(F'Invoked upon upload of a file without .json in its Path().suffixes: {src_s3_path}')
        s3 = boto3.client('s3')
        tmpdir = tempfile.TemporaryDirectory()
        diff_file_path = Path(tmpdir.name, src_s3_path.name)
        rem = re.match(r'^(?P<datetime>\d{8}T\d{6}Z)', diff_file_path.name)
        diff_datetime = dateutil.parser.parse(rem.group('datetime'))
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
        #BEGIN insert records
        records_inserted = 0
        if es_bulk_batch_size > 1:
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
                        records_inserted += 1
                    else:
                        raise ValueError(F'bulk insert returned an unsuccessful result: {bulk_action_result}')
                progress_bar.update(records_inserted_this_batch)
            progress_bar.close()
        else:
            for vrp_diff_record in diff_data['vrp_diffs']:
                vrp_diff_obj = VrpDiff.from_json_obj(vrp_diff_record)
                vrp_diff_obj.es_insert(
                    diff_datetime=diff_datetime,
                    es_client=es_client,
                    es_index=es_index,
                )
                records_inserted += 1
        #DONE inserting records
        runtime = time.time() - realtime_initial
        retdict = {
            'records_inserted': records_inserted,
            'runtime': runtime,
        }
        return retdict

def aws_lambda_entry_point(event, context):
    retval = VrpDiff.aws_lambda_entry_point(event, context)
    return retval

def aws_lambda_entry_point_import(event, context):
    retval = VrpDiff.aws_lambda_entry_point_import(event, context)
    return retval
