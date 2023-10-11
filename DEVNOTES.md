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
	]
}
```

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
]
}
```

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
