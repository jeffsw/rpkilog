# Data source(s)

job suggests fetching https://console.rpki-client.org/vrps.json every 5m
and using that as a source of changes.  This makes sense later on.  In the
short term, I care more about past history; so I'll come back to this.

rpkiviews.org lists some archives including josephine.sobornost.net.

http://josephine.sobornost.net/josephine.sobornost.net/rpkidata/ has that
history in its tar files, e.g. rpki-dateTtimeZ/output/rpki-client.json
contains the same data schema as vrps.json:

```json
{
    "metadata": {
        "buildmachine": "josephine",
        "buildtime": "2021-11-21T00:07:00Z",
        ...
    },
    "roas": [
        { "asn": 13335, "prefix": "1.0.0.0/24", "maxLength": 24, "ta": "apnic", "expires": 1637590711 },
        { "asn": 38803, "prefix": "1.0.4.0/24", "maxLength": 24, "ta": "apnic", "expires": 1637584003 },
        ...
    ],
	"bgpsec_keys": [
		{ "asn": 15562, "ski": "5D4250E2D81D4448D8A29EFCE91D29FF075EC9E2", "pubkey": "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEgFcjQ/g//LAQerAH2Mpp+GucoDAGBbhIqD33wNPsXxnAGb+mtZ7XQrVO9DQ6UlAShtig5+QfEKpTtFgiqfiAFQ==", "ta": "ripe", "expires": 1668013479 },
		{ "asn": 15562, "ski": "BE889B55D0B737397D75C49F485B858FA98AD11F", "pubkey": "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE4FxJr0n2bux1uX1Evl+QWwZYvIadPjLuFX2mxqKuAGUhKnr7VLLDgrE++l9p5eH2kWTNVAN22FUU3db/RKpE2w==", "ta": "ripe", "expires": 1668013483 }
	],
}

# VRP Cache diffs we generate 

I'm generating what I think is appropriately named *VRP Cache diffs* in the
below JSON structure (abbreviated for brevity).  The output is easy to grep
as each *diff* is a single line.

```json
{
"object_type": "rpkilog_vrp_cache_diff_set",
"metadata": {
    "vrp_cache_old": {
        ... copy of metadata from old input file ...
    },
    "vrp_cache_new": {
        ... copy of metadata from new input file ...
    },
    ...
},
"vrp_diffs": [
    { "verb": "REPLACE", "old_roa": { "prefix": "192.0.2.0/24", "maxLength": 22, "asn": 64496, "expires": 1637509817, "ta": "test" }, "new_roa": { "prefix": "192.0.2.0/24", "maxLength": 24, "asn": 64496, "expires": 1637539219, "ta": "test" } },
],
}
```

# More data?

I'd like to add a few more fields to each ROA record:

* version
* serial
* notBefore

## RPKI Data Schema

We cannot look up ROAs on-disk given a known ASN and/or prefix.  I think we need
to read all the ROAs and populate an index.  This will be an exercise for
a second revision of the project.

The ROA files have an SHA256 filename.  There's also what looks like a
UUID in the directory path.  I'd like to understand the filesystem
naming scheme.

Here is an example ROA as displayed by rpki-client.org (great tool!):

http://console.rpki-client.org/rsync/rpki.ripe.net/repository/DEFAULT/3b/2434f8-0566-45fc-b714-31a3ecf1bdb6/1/qNoePrBnj7oy5vHRLFafqCQNoc8.roa.html

ROA fields include:

* Issuer CN is associated with the issuing authority, e.g. RIPE
* Subject CN ???
* sbgp-ipAddrBlock gives the prefix
* Where is the ASN and max prefix length ???

# Indexing implementation thoughts

If we need I/O performance to index the ROAs, one option may be to use
EC2 instance storage.  Relevant instance-types:

| Instance Type | vCPUs | GHz | RAM | SSD | On-Demand $ Per 720 Hours |
| c5ad.large    |     2 | 3.3 |   4 |  75 |                     $  62 |
| mdad.large    |     2 | 2.4 |   8 |  75 |                     $  75 |
| c5ad.xlarge   |     4 | 3.3 |   8 | 150 |                     $ 124 |

# ElasticSearch records for changes

We need to be able to query shorter prefixes.  That's essential to finding out what ROAs could have
affected a given prefix.  I think this means we need to send queries for all shorter routes, like:

Something like this could work:
```json
{
    "asn": 64496, "prefix": "2001:db8::/32", "maxLength": 48, "ta": "test-rir", "expires": 12345
}
```

```json
# GET range_index/_search
{
    "query": {
        "prefix": {
            "addr": {
                "192.0.2.0/24"
            }
        },
        # or ?  how to express this in elasticsearch?
        "prefix": {
            "addr": {
                "192.0.2.0/23"
            }
        },
        # repeat until /0
        "prefix": {
            "addr": {
                "192.0.0.0/22"
            }
        }
        # should also constrain the maxLength for each of these
        # let's put some data into ES and experiment
    }
}
```
