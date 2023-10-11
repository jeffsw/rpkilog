[rpkilog.com](https://rpkilog.com) is a work in progress, but you can query it today for real data.  All
source code is contained in this repo, including all the Terraform necessary to instantiate the AWS resources
for hosting it.  Contributions welcome!

# Data ingest from RPKI system

We check for updated VRP cache snapshots every 10 minutes.  When one is found, the VRP summary we need
is extracted and uploaded to the `rpkilog-snapshot-summary` bucket.  From then, an event-driven pipeline
processes the data using two Lambda functions, and inserts it into ElasticSearch.

Both the snapshot-summaries and diffs are retained in S3 so we can easily reprocess data in the future.

```mermaid
flowchart LR
    rpki_archive>RPKI VRP\ncache snapshot]
    rpki-archive-site-crawler[[rpki-archive-site-crawler\ncron job]]
    s3_snapshot_summary[(rpkilog-snapshot-summary\nS3)]
    vrp_cache_diff[[vrp_cache_diff\nLambda]]
    s3_diff[(rpkilog-diff\nS3)]
    diff_import[[diff_import\nLambda]]
    elasticsearch[(es-prod\nElasticSearch DB)]

    rpki_archive --> rpki-archive-site-crawler
    rpki-archive-site-crawler --> s3_snapshot_summary
    s3_snapshot_summary --> vrp_cache_diff
    vrp_cache_diff --> s3_diff
    s3_diff --> diff_import
    diff_import --> elasticsearch
```

```mermaid
sequenceDiagram
    autonumber

    participant cron1
    participant lambda
    participant s3
    participant es
    participant rpki_archive

    Note right of cron1: get rpki archive tgz files
    cron1-->>cron1: cron job: rpkilog-archive-site-crawler
    activate cron1
        cron1->s3: list rpki-snapshot and rpki-snapshot-summary buckets
        cron1->rpki_archive: web crawl: list files after given date
        loop tgz_download
            rpki_archive->>cron1: new tgz file(s)
            cron1->>s3: upload new tgz file(s) to rpkilog-snapshot bucket
            cron1->>s3: upload new summary file(s) to rpkilog-snapshot-summary bucket
        end
    deactivate cron1

    Note right of cron1: use JSON summary to generate VRP cache diff
    s3-->>lambda: S3 EVENT: new file arrived in rpkilog-snapshot-summary bucket.  Invoke vrp_cache_diff.
    activate lambda
    s3->>lambda: list files in rpkilog-snapshot-summary bucket
    s3->>lambda: get newly-arrived JSON summary file
    s3->>lambda: get previous JSON summary file by date
    Note right of lambda: generate VRP cache diff
    lambda->>s3: upload <newly-arrived-date>.vrpdiff.json.gz
    deactivate lambda

    Note right of cron1: insert VrpDiff objects into ElasticSearch
    s3-->>lambda: S3 EVENT: new file arrived in rpkilog-diff bucket.  Invoke diff_import.
    activate lambda
    loop
        Note right of lambda: Typically thousands of diff-records.<br>Insert 100 to 1000 at once.
        lambda->>es: bulk insert
        activate es
        alt
            es->>lambda: 429 TOO_MANY_REQUESTS
            Note right of lambda: Watch for error TOO_MANY_REQUESTS.<br>Delay and retry as needed.
        else
            es->>lambda: SUCCESS
        end
        deactivate es
    end
    deactivate lambda

```

### Installing from github

```bash
pip3 install --upgrade "git+https://github.com/jeffsw/rpkilog.git#subdirectory=python/rpkilog"
```

# ElasticSearch query examples

> ⚡ For users who would like to query the ElasticSearch database directly instead of via the https://rpkilog.com
web site or HTTP API, some examples will be provided here.

### Lucene syntax

Lucene syntax is unforgiving in that the database generally won't give you an error message when executing
a query with many kinds of malformations.  For example, `maxLength:>=24` requires that `:` after the field
name, but if omitted, the database is likely to silently match zero records.

```lucene
prefix:"192.0.2.5" AND maxLength:>=24
```
