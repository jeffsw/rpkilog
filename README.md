rpkilog.com is a work in progress.

TODO: insert ref to pipeline.mmd here

# Data ingest from RPKI system

A cron job, two lambda functions, and two S3 buckets are involved in the data ingest process.

```mermaid
flowchart LR
    rpki_archive
    rpki-archive-site-crawler
    s3_snapshot_summary
    vrp_cache_diff
    s3_diff
    diff_import
    elasticsearch

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

### Lucene query example

Lucene syntax is unforgiving in that the database generally won't give you an error message when executing
a query with many kinds of malformations.  For example, `maxLength:>=24` requires that `:` after the field
name, but if omitted, the database is likely to silently match zero records.

```lucene
prefix:"192.0.2.5" AND maxLength:>=24
```
