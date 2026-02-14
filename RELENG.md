The "release" process could use work.

# CLI End-to-End Testing

ℹ️ These tools are primarily used on the back-end and there aren't any other known use-cases.

## rpkilog-routinator-vrp-fetcher

```shell
export AWS_PROFILE=rpkilog
rpkilog-routinator-vrp-fetcher \
  --snapshot-dir ~/src/rpkilog/tmp \
  --summary-dir ~/src/rpkilog/tmp \
  --snapshot-upload s3://rpkilog-test/ \
  --summary-upload s3://rpkilog-test/

```

# QA End-to-End GUI Testing

I don't know how to automate browser end-to-end testing.  We'll rely on manual tests for now.  Writing
them down will at least help avoid regressions in "production".

* ensure some reliable public resources with ROAs appear in search results:
  * 8.8.8.8
  * 2001:4860:4860::8888 (avoid regression fixed by [PR#38](https://github.com/jeffsw/rpkilog/pull/38))
  * 2001:4860:4860::/48 
* check for ROAs with ASN `0` (blocked from being advertised) ([GH-35](https://github.com/jeffsw/rpkilog/issues/35))

# Verification Post-Release Back-End

* ensure new **vrp cache snapshots** are being downloaded into the `rpkilog-snapshot` S3 bucket at the
intended interval (currently every 20 minutes)
* ensure new **snapshot summary** files are being produced into the `rpkilog-snapshot-summary` S3 bucket
on similar intervals as the `rpkilog-snapshot` files are downloaded; and these files are not empty or
very small.  Typical size is now > 1MB with bz2 compression.
* ensure new **vrpdiff** files are being produced into the `rpkilog-diff` S3 bucket on similar intervals
as the above two file-types.  Diffs usually aren't empty.  Files commonly range from 11 KB to 2.2 MB.
