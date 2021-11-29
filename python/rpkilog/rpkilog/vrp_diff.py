#!/usr/bin/env python
import argparse
import getpass
import logging
import json
import os
from pathlib import Path
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
    def cli_entry_point(cls):
        realtime_initial = time.time()
        logging.basicConfig()
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
        
        with open(args['old_file'], 'r') as f:
            logger.info(F'Loading old data from {args["old_file"]}')
            vrp_cache_old = json.load(f)
        with open(args['new_file'], 'r') as f:
            logger.info(F'Loading new data from {args["new_file"]}')
            vrp_cache_new = json.load(f)

        if args['overwrite']:
            result_file = open(args['result_file'], 'w')
        else:
            result_file = open(args['result_file'], 'x')
        logger.info(F'Diff-ing {len(vrp_cache_old["roas"])} old and {len(vrp_cache_new["roas"])} new records ...')
        diff_objs = cls.vrp_diff_list(
            old_roas=vrp_cache_old['roas'],
            new_roas=vrp_cache_new['roas']
        )

        realtime_delta = time.time() - realtime_initial
        times = os.times()
        result_metadata = {
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
                'filename': str(args['old_file']),
                'metadata': vrp_cache_old['metadata'],
            },
            'vrp_cache_new': {
                'filename': str(args['new_file']),
                'metadata': vrp_cache_new['metadata'],
            },
        }
        try:
            import psutil
            memory_use_rss = psutil.Process().memory_info().rss
            result_metadata['memory_use_rss_mb'] = int(memory_use_rss / 1048576)
        except:
            logger.info(F'Unable to invoke psutil.Process().memory_info() to get RAM use.  Omitting it from metadata.')
            pass

        logger.info(F'Writing results to JSON file {args["result_file"]}')
        result_file.write(F'''{{
"object_type": "rpkilog_vrp_cache_diff_set",
"metadata": {json.dumps(result_metadata, indent=4, sort_keys=True)},
"vrp_diffs": [
''')

        for idx in range(len(diff_objs)):
            diff_obj = diff_objs[idx]
            if idx < len(diff_objs) - 1:
                separator = ',\n'
            else:
                separator = '\n'
            diff_str = diff_obj.as_json_str()
            result_file.write('    ' + diff_str + separator)
        result_file.write(']\n}\n')
