from __future__ import annotations
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_boto3_s3.service_resource import Bucket, ObjectSummary


def list_s3_object_previous(
        bucket: Bucket,
        subject_datetime: datetime,
        prefix_fstr: str = "{datetime_prefix}",
) -> str:
    """
    Using the boto3 s3 bucket resource interface, given the bucket object, list objects in the
    bucket with datetime-based filenames as specified in the prefix_fstr arg.  Return the object key
    found in the bucket which is immediately before the given subject_datetime.

    Searches the given day first, e.g. datetime_prefix=YYYYMMDD.  If no object keys found which sort
    less-than the given subject_datetime, searches the given month timeframe with datetime_prefix=YYYYMM.
    If no object keys found within that month, searches the previous month (which might be in a previous
    year).  If nothing found one month previous, continues searching previous months up to 12 months
    previous.  If still no matches, raises a KeyError.

    The key comparison is lexicographic: a probe key is constructed as
    ``prefix_fstr.format(datetime_prefix=subject_datetime.strftime('%Y%m%dT%H%M%SZ'))`` and only
    object keys that sort strictly below it are considered.  This works correctly as long as the
    datetime embedded in the key uses ISO-like ordering (YYYYMMDD...).

    Args:
        bucket: boto3 bucket resource from e.g. boto3.resource('s3').Bucket('my_bucket')
        subject_datetime: find an S3 object immediately *before* the given datetime
        prefix_fstr: format string (default: '{datetime_prefix}') used by S3 list operations.  This might
            be something like 'summary-{datetime_prefix}' or 'source-name-{datetime_prefix}'.  It MUST
            contain '{datetime_prefix}'.  If that doesn't appear to be in the argument a ValueError
            exception will be raised.

    Returns:
        S3 object key name

    Raises:
        ValueError: If "{datetime_prefix}" is omitted from prefix_fstr

        KeyError: If no object can be found in the bucket matching the given prefix_fstr and sorting
            before the given subject_datetime
    """
    if -1 == prefix_fstr.find('{datetime_prefix}'):
        raise ValueError(
            f'prefix_fstr argument missing MANDATORY {{datetime_prefix}}; given argument is: {prefix_fstr}'
        )

    # Lexicographic upper bound: any key < probe sorts before subject_datetime
    probe = prefix_fstr.format(datetime_prefix=subject_datetime.strftime('%Y%m%dT%H%M%SZ'))

    def candidates_for(datetime_prefix_str: str) -> list[str]:
        prefix = prefix_fstr.format(datetime_prefix=datetime_prefix_str)
        found = []
        for obj in bucket.objects.filter(Prefix=prefix):
            if obj.key < probe:
                found.append(obj.key)
        return found

    # Search current day
    found = candidates_for(subject_datetime.strftime('%Y%m%d'))
    if found:
        return max(found)

    # Search current month (covers earlier days in the same month)
    found = candidates_for(subject_datetime.strftime('%Y%m'))
    if found:
        return max(found)

    # Search previous months, up to 12
    for months_back in range(1, 13):
        raw_month = subject_datetime.month - months_back
        year = subject_datetime.year + (raw_month - 1) // 12
        month = ((raw_month - 1) % 12) + 1
        found = candidates_for(f'{year:04d}{month:02d}')
        if found:
            return max(found)

    raise KeyError(f'No S3 object found before {subject_datetime} with prefix_fstr={prefix_fstr!r}')


def list_s3_snapshot_files_within_range(
        bucket: Bucket,
        start_datetime: datetime,
        end_datetime: datetime,
) -> set[ObjectSummary]:
    """
    Returns the S3 object summaries for snapshot files within the given start_datetime ... end_datetime range.

    The given range is approximate; we query the S3 API by day, e.g. prefix: `rpki-20260430T`.
    """
    retval = set()
    time_range = end_datetime - start_datetime
    for day_offset in range(time_range.days + 1):
        day = start_datetime + timedelta(days=day_offset)
        snapshot_prefix = 'rpki-' + day.strftime('%Y%m%dT')
        objects = bucket.objects.filter(Prefix=snapshot_prefix)
        for obj in objects:
            retval.add(obj)
    return retval


def list_s3_summary_files_within_range(
        bucket: Bucket,
        start_datetime: datetime,
        end_datetime: datetime,
) -> set[ObjectSummary]:
    """
    Returns the S3 object summaries for summary files within the given start_datetime ... end_datetime range.

    The given range is approximate; we query the S3 API by day, e.g. prefix: `20260501T`.
    """
    retval = set()
    time_range = end_datetime - start_datetime
    for day_offset in range(time_range.days + 1):
        day = start_datetime + timedelta(days=day_offset)
        prefix = day.strftime('%Y%m%dT')
        objects = bucket.objects.filter(Prefix=prefix)
        for obj in objects:
            retval.add(obj)
    return retval
