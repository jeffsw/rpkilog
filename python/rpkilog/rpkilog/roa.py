from datetime import datetime
import re

import dateutil.parser
import netaddr


class Roa():
    def __init__(
            self,
            asn: int,
            prefix: netaddr.IPNetwork,
            maxLength: int,
            ta: str,
            expires: int = 0,
            source_host: str = None,
            source_time: datetime = None,
    ):
        if isinstance(asn, str) and asn.startswith('AS'):
            # tolerate old VRP Cache files with asn="AS64496" instead of asn=64496
            rem = re.match(r'^AS(?P<asn>\d+)$', asn)
            if not rem:
                raise ValueError(F'Cannot get integer ASN from asn argument passed as string: {asn}')
            asn = int(rem.group('asn'))
        if asn < 0 or asn > 2 ** 32 - 1:
            raise ValueError(F'Invalid asn F{asn}')
        self.asn = int(asn)
        if not isinstance(prefix, netaddr.IPNetwork):
            prefix = netaddr.IPNetwork(prefix)
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
        if source_host is not None:
            self.source_host = source_host
        if source_time is not None:
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

    @classmethod
    def new_from_routinator_jsonext(
            cls,
            routinator_json: dict,
            source_host: str = None,
            source_time: datetime = None,
    ):
        """
        Routinator `jsonext` format is different than rpki-client's and contains a *list* of source attestations
        associated with a given `(asn, prefix, maxLength)` combination.

        TODO: From the *list* of attestations I'm just picking the first entry.  This might be wrong.

        See also: https://routinator.docs.nlnetlabs.nl/en/stable/output-formats.html#term-jsonext

        >>> routinator_roa = \
            [{'asn': 'AS13335',
              'maxLength': 24,
              'prefix': '1.0.0.0/24',
              'source': [{'chainValidity': {'notAfter': '2025-03-15T14:17:32Z',
                                            'notBefore': '2025-03-09T17:50:01Z'},
                          'stale': '2025-03-15T14:17:31Z',
                          'tal': 'apnic',
                          'type': 'roa',
                          'uri': 'rsync://rpki.apnic.net/member_repository/A91872ED/ED8C96901D6C11E28A38A3AD08B02CD2/797B4DEC293B11E8B187196DC4F9AE02.roa',
                          'validity': {'notAfter': '2031-03-31T00:00:00Z',
                                       'notBefore': '2021-02-11T14:20:11Z'}
                         }]
             }]
        >>> roa = Roa.new_from_routinator_jsonext(routinator_json=routinator_roa)
        """  # noqa E501
        if missing := {'asn', 'prefix', 'maxLength'} - routinator_json.keys():
            raise KeyError(f'argument routinator_json dict is missing required keys: {missing}; arg: {routinator_json}')
        selected_source = routinator_json['source'][0]
        constructor_args = {
            'prefix': routinator_json['prefix'],
            'maxLength': routinator_json['maxLength'],
            'ta': selected_source['tal'],
        }
        if type(routinator_json['asn'] == int):
            constructor_args['asn'] = routinator_json['asn']
        elif rem := re.match(r'^AS(?P<asn>\d+)$', routinator_json['asn']):
            constructor_args['asn'] = rem.group('asn')
        else:
            raise ValueError(f'unrecognizable asn field in ROA: {routinator_json}')
        constructor_args['expires'] = int(dateutil.parser.parse(selected_source['stale']).timestamp())

        if source_host:
            constructor_args['source_host'] = source_host
        if source_time:
            constructor_args['source_time'] = source_time
        retval = cls(**constructor_args)
        return retval

    @classmethod
    def new_from_rpkiclient_json(
            cls,
            rpkiclient_json: dict,
            source_host: str = None,
            source_time: datetime = None,
    ):
        constructor_args = {
            **rpkiclient_json,
            'source_host': source_host,
            'source_time': source_time,
        }
        retval = cls(**constructor_args)
        return retval

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
