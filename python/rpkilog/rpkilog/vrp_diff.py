#!/usr/bin/env python
import argparse
import boto3
import bz2
from datetime import datetime
import dateutil.parser
import getpass
import logging
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import netaddr

logger = logging.getLogger(__name__)

class Roa():
    def __init__(
        self,
        asn:int,
        prefix:netaddr.IPNetwork,
        maxLength:int,
        ta:str,
        expires:int,
        source_host:str=None,
        source_time:datetime=None,
    ):
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
        # load JSON data from both files
        old_file = open(old_file_path)
        old_data = json.load(old_file)
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
        # return result_metadata
        return result_metadata

    @classmethod
    def vrp_diff_list(cls, old_roas:list, new_roas:list) -> list:
        '''
        Given two lists of VRPs, return a list of VrpDiff objects.
        EMPTIES THE INPUT LISTS as a side-effect.  Pass copies if you don't want that!

        This function assumes both ROA lists are sorted by prefix, then by ASN.  If they're not, it
        will raise an error.  Such an error would indicate the implementation needs to support
        un-sorted input, or caller needs to sort the input before invoking this method.

        SCALE: This could return a generator which reads the input files (or lists) sequentially and
        generates results as-needed.  It would be possible to scale up to a much larger VRP Cache
        without using much RAM.
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
        while len(old_roas) + len(new_roas) > 0:
            # Every time through the loop, we must pop one entry from one or both input lists.
            # If we don't, we're stuck, and that's a bug.  That's why we check.
            if not len(old_roas) + len(new_roas) < input_roa_count:
                raise Exception('STUCK not making progress consuming input ROAs')
            input_roa_count = len(old_roas) + len(new_roas)
            # If either old_roas or new_roas is empty, old_next or new_next will be None.
            old_next = Roa(**old_roas[0]) if len(old_roas) else None
            new_next = Roa(**new_roas[0]) if len(new_roas) else None
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
            logging.warning(F'ONLY ONE FILE IN src_bucket {src_bucket_name}.  Is this first ever invocation?')
            return
        # find the filename immediately before the one which invoked us
        for candidate_filename in sorted(summaries, reverse=True):
            rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.json$', candidate_filename)
            if not rem:
                logging.warning(F'{src_bucket_name} contained a file not matching our regex: {candidate_filename}')
                continue
            candidate_datetime = dateutil.parser.parse(rem.group('datetime'))
            if candidate_datetime < new_file_datetime:
                # We reverse-sorted the list of files, so the first one with an earlier datetime should be right
                old_file_key = candidate_filename
                return(old_file_key)
        else:
            # no files found which are older than new_file_datetime
            logging.warning(
                F'{src_bucket_name} doesnt contain any files older than {new_file_datetime}'
                F' Is this first ever invocation?'
            )
            return

    @classmethod
    def aws_lambda_entry_point(cls, event, context):
        logging.basicConfig(
            level='INFO',
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
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
    def cli_entry_point(cls):
        realtime_initial = time.time()
        logging.basicConfig(level='INFO')
        ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
        ap.add_argument('--old-file', required=True, type=Path, help='Old input JSON file')
        ap.add_argument('--new-file', required=True, type=Path, help='New input JSON file')
        ap.add_argument('--overwrite', default=False, action='store_true', help='Overwrite existing result file')
        ap.add_argument('--result-file', required=True, type=Path, help='Results are saved in JSON format to this file')
        ap.add_argument('--log-level', type=str, help='Log level.  Try CRITICAL, ERROR, INFO (default) or DEBUG.')
        args = vars(ap.parse_args())
        if 'log_level' in args:
            logger.setLevel(args['log_level'])
        else:
            logger.setLevel('INFO')

        metadata = cls.vrp_diff_from_files(
            old_file_path=args['old_file'],
            new_file_path=args['new_file'],
            output_file_path=args['result_file'],
            output_file_mode='wt' if args['overwrite'] else 'xt',
            realtime_initial=realtime_initial,
        )
        print(json.dumps(metadata))

    @classmethod
    def generic_entry_point(
        cls,
        src_bucket_name:str,
        new_file_key:str,
        diff_bucket_name:str,
        tmp_dir:Path=None,
    ):
        '''
        Invoke by cli_entry_point or aws_lambda_entry_point.
        '''
        realtime_initial = time.time()
        logging.info(F'Invoked for new_file_key={new_file_key}')
        if tmp_dir==None:
            tmp_dir = Path('/tmp')
        s3 = boto3.client('s3')
        new_file_path = Path(tmp_dir, new_file_key)
        rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.json$', new_file_key)
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
        old_file_path = Path(tmp_dir, old_file_key)
        rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.json$', old_file_key)
        if not rem:
            raise ValueError(F'Old file key didnt match our regex: {old_file_key}')
        logging.info(F'Downloading files from S3 bucket {src_bucket_name} {old_file_key} {new_file_key}')
        s3.download_file(Bucket=src_bucket_name, Key=old_file_key, Filename=str(old_file_path))
        s3.download_file(Bucket=src_bucket_name, Key=new_file_key, Filename=str(new_file_path))
        metadata = cls.vrp_diff_from_files(
            old_file_path=old_file_path,
            new_file_path=new_file_path,
            output_file_path=output_file_path,
            realtime_initial=realtime_initial,
        )
        s3.upload_file(
            Filename=str(output_file_path),
            Bucket=diff_bucket_name,
            Key=output_file_key,
        )
        return metadata

def aws_lambda_entry_point(event, context):
    retval = VrpDiff.aws_lambda_entry_point(event, context)
    return retval
