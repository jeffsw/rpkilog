from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_boto3_s3.service_resource import Bucket, ObjectSummary

# Above this many days, list_s3_summary_files_within_range switches from one S3 list request per
# day to a single listing of the whole prefix, filtered client-side.
LIST_PER_DAY_MAX_DAYS = 366


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
        prefix: str = '',
) -> set[ObjectSummary]:
    """
    Returns the S3 object summaries for snapshot files within the given start_datetime ... end_datetime range.

    The given range is approximate; we query the S3 API by day, e.g. prefix: `rpki-20260430T`.
    If a `prefix` is given, it is prepended to that per-day prefix (snapshot keys themselves
    always begin 'rpki-').

    Ranges spanning more than LIST_PER_DAY_MAX_DAYS days are handled with a single listing of
    the whole `prefix` instead of one list request per day, mirroring
    list_s3_summary_files_within_range; both paths return the same objects.
    """
    retval = set()
    time_range = end_datetime - start_datetime
    key_prefix = prefix + 'rpki-'
    if time_range.days + 1 > LIST_PER_DAY_MAX_DAYS:
        first_day_str = start_datetime.strftime('%Y%m%dT')
        last_day_str = end_datetime.strftime('%Y%m%dT')
        for obj in bucket.objects.filter(Prefix=key_prefix):
            # equivalent to the per-day path: key must continue with an in-range YYYYMMDDT
            day_part = obj.key[len(key_prefix):len(key_prefix) + 9]
            if not re.fullmatch(r'\d{8}T', day_part):
                continue
            if first_day_str <= day_part <= last_day_str:
                retval.add(obj)
    else:
        for day_offset in range(time_range.days + 1):
            day = start_datetime + timedelta(days=day_offset)
            composite_prefix = key_prefix + day.strftime('%Y%m%dT')
            objects = bucket.objects.filter(Prefix=composite_prefix)
            for obj in objects:
                retval.add(obj)
    return retval


def list_s3_summary_files_within_range(
        bucket: Bucket,
        start_datetime: datetime,
        end_datetime: datetime,
        prefix: str = '',
) -> set[ObjectSummary]:
    """
    Returns the S3 object summaries for summary files within the given start_datetime ... end_datetime range.

    The given range is approximate; we query the S3 API by day, e.g. prefix: `20260501T`.
    If a `prefix` is given, it is prepended to that per-day date prefix.

    Ranges spanning more than LIST_PER_DAY_MAX_DAYS days are handled with a single listing of the
    whole `prefix` instead of one list request per day; the results are filtered client-side to
    the same per-day granularity, so both paths return the same objects.

    Example, listing files under an --s3-summary-prefix like s3://rpkilog-snapshot-summary/summaries/
    for a --datetime-min ... --datetime-max range, as in reconcile.py:

        bucket = boto3.resource('s3').Bucket('rpkilog-snapshot-summary')
        summary_objects = list_s3_summary_files_within_range(
            bucket=bucket,
            start_datetime=args.datetime_min,
            end_datetime=args.datetime_max,
            prefix='summaries/',
        )
    """
    retval = set()
    time_range = end_datetime - start_datetime
    if time_range.days + 1 > LIST_PER_DAY_MAX_DAYS:
        first_day_str = start_datetime.strftime('%Y%m%dT')
        last_day_str = end_datetime.strftime('%Y%m%dT')
        for obj in bucket.objects.filter(Prefix=prefix):
            # equivalent to the per-day path: key must continue with an in-range YYYYMMDDT
            day_part = obj.key[len(prefix):len(prefix) + 9]
            if not re.fullmatch(r'\d{8}T', day_part):
                continue
            if first_day_str <= day_part <= last_day_str:
                retval.add(obj)
    else:
        for day_offset in range(time_range.days + 1):
            day = start_datetime + timedelta(days=day_offset)
            composite_prefix = prefix + day.strftime('%Y%m%dT')
            objects = bucket.objects.filter(Prefix=composite_prefix)
            for obj in objects:
                retval.add(obj)
    return retval
