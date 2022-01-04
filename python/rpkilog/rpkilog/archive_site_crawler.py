#!/usr/bin/env python
'''
Crawl an HTTP index of RPKI archive data and download desirable files.

Upload those files to S3.

TODO: Move to its own module.
'''
import argparse
import boto3
import bz2
from datetime import datetime, timedelta
import dateutil
from html.parser import HTMLParser
import inspect
from inspect import Parameter
import json
import logging
import os
import re
import requests
from pathlib import Path
import re
import tarfile
from urllib.parse import urlparse
import urllib.request

logger = logging.getLogger()

class MyHTMLParser(HTMLParser):
    '''
    Subclass for extracting useful URLs from RPKI archive web index pages.  Invoke like:

    parser = MyHTMLParser()
    parser.feed(page_blob)
    '''
    def __init__(self, page_url:str):
        super(MyHTMLParser, self).__init__()
        self.href_urls = set()
        self.page_url = page_url

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        if tag != 'a':
            return
        attrdict = dict(attrs)
        if 'href' not in attrdict:
            return
        parsed = urlparse(attrdict['href'])
        if parsed.netloc:
            # absolute url
            found_url = attrdict['href']
        else:
            found_url = self.page_url + attrdict['href']
        self.href_urls.add(found_url)

class ArchiveSiteCrawler():
    '''
    Web-crawl an RPKI archive site.  Retrieve TAR files we haven't previously downloaded (by comparing)
    '''

    @classmethod
    def extract_matching_file_from_tar(
        cls,
        input_tar:Path,
        output_dir:Path,
        find_file_re:str=None,
        bzip_result_file:bool=True,
    ) -> Path:
        '''
        Extract file matching find_file_re from given TAR file.  Name the resulting file based on contatenation
        of the regex match groups.  Optionally, bzip the file and add '.bz2' to the filename.

        Returns a Path object to the resulting file on disk.
        '''
        if find_file_re==None: find_file_re=r'^rpki-(\d{8}T\d{6}Z)/output/rpki-client(.json)$'
        logger.info(F'Extracting useful JSON data from {input_tar}')
        tf = tarfile.open(name=input_tar, mode='r')
        for member in tf.getmembers():
            if not member.isfile():
                continue
            rem = re.match(find_file_re, member.name)
            if not rem:
                continue
            result_file_name = ''.join(rem.groups())
            if not len(result_file_name):
                raise ValueError(F'Matching file {member.name} has no regex groups matching. Need those for filename.')
            ef = tf.extractfile(member)
            if bzip_result_file:
                result_path = Path(output_dir, result_file_name + '.bz2')
                output_file = bz2.open(result_path, mode='xb')
            else:
                result_path = Path(output_dir, result_file_name)
                output_file = open(result_path, 'xb')
            output_file.write(ef.read())
            output_file.close()
            return result_path
        else:
            raise KeyError(F'No matching file found in TAR file {input_tar}')

    @classmethod
    def fetch_day_urls_from_month_page(cls, month_page_url:str, site_root:str, start_date:datetime) -> set:
        '''
        Fetch a "month page," which contains a list of links to pages for individual days.

        Parse that page and find all the URLs of day-pages.
        Excluse any days before start_date.

        Return a set containing the appropriate day-page URLs.
        '''
        logger.info(F'FETCHING month page {month_page_url}')
        urls_on_month_page = cls.fetch_page_href_urls(page_url=month_page_url)
        day_urls = set()
        for url in sorted(urls_on_month_page):
            if not url.startswith(month_page_url):
                continue
            relative_url = url[len(site_root):]
            rem = re.match(r'\/?(?P<date>(?P<year>\d{4})\/(?P<month>\d{2})\/(?P<day>\d{2}))\/', relative_url)
            if not rem:
                continue
            if dateutil.parser.parse(rem.group('date')) < start_date:
                logger.debug(F'Not crawling into {relative_url} because it is before {start_date.isoformat()}')
                continue
            day_urls.add(url)
        return(day_urls)

    @classmethod
    def fetch_month_urls_from_year_page(cls, year_page_url:str, site_root:str, start_date:datetime) -> set:
        '''
        Fetch the "year page," conaining a list of links to month-pages.

        Parse that page and find all the URLs of the month-pages.
        Exclude month-pages before the start_date.

        Return a set containing the desired month-page URLs.
        '''
        logger.info(F'FETCHING year page {year_page_url}')
        urls_on_year_page = cls.fetch_page_href_urls(page_url=year_page_url)
        month_urls = set()
        for url in sorted(urls_on_year_page):
            if not url.startswith(year_page_url):
                continue
            relative_url = url[len(site_root):]
            rem = re.match(r'\/?(?P<year>\d{4})\/(?P<month>\d{2})\/', relative_url)
            if not rem:
                continue
            if (int(rem.group('year')) == start_date.year) and (int(rem.group('month')) < start_date.month):
                logger.debug(F'Not crawling into {relative_url} because it is before {start_date.isoformat()}')
                continue
            month_urls.add(url)
        return month_urls

    @classmethod
    def fetch_tar_urls_from_archive_site(cls, site_root:str, start_date:datetime) -> set:
        '''
        Crawl the specified RPKI archive site_root and get the URLs of TARs beginning with start_date.

        Return the URLs in a set.
        '''
        desired_tar_urls = set()
        year_urls = cls.fetch_year_urls_from_root_page(site_root=site_root, start_date=start_date)
        for y_url in sorted(year_urls):
            month_urls = cls.fetch_month_urls_from_year_page(
                year_page_url=y_url,
                site_root=site_root,
                start_date=start_date
            )
            for m_url in sorted(month_urls):
                day_urls = cls.fetch_day_urls_from_month_page(
                    month_page_url=m_url,
                    site_root=site_root,
                    start_date=start_date
                )
                for d_url in sorted(day_urls):
                    tar_file_urls = cls.fetch_tar_urls_from_day_page(
                        day_page_url=d_url,
                        site_root=site_root,
                        start_date=start_date
                    )
                    for t_url in tar_file_urls:
                        desired_tar_urls.add(t_url)
        return(desired_tar_urls)

    @classmethod
    def fetch_tar_urls_from_day_page(cls, day_page_url:str, site_root:str, start_date:datetime) -> set:
        '''
        Fetch the "day page," which contains a list of files for a given date.
        
        Parse that page and find all the URLs of RPKI archive TARs on the page.
        Ignore any RPKI archive filenames with datetime-based name before start_date.

        Return a set containing the TAR URLs.
        '''
        logger.info(F'FETCHING day page {day_page_url}')
        urls_on_day_page = cls.fetch_page_href_urls(page_url=day_page_url)
        tar_file_urls = set()
        for url in sorted(urls_on_day_page):
            if not url.startswith(day_page_url):
                continue
            relative_url = url[len(site_root):]
            rem = re.search(r'rpki-(?P<datetime>\d{8}T\d{6})Z.tgz$', relative_url)
            if not rem:
                continue
            if dateutil.parser.parse(rem.group('datetime')) < start_date:
                logger.debug(F'Not crawling into {relative_url} because it is before {start_date.isoformat()}')
                continue
            tar_file_urls.add(url)
        return(tar_file_urls)

    @classmethod
    def fetch_year_urls_from_root_page(cls, site_root:str, start_date:datetime) -> set:
        '''
        Fetch the "site root," which contains a list of links to year-pages.

        Parse that "site root" page and find the year-page URLs on it.
        Ignore any year-URLs before start_date.

        Return a set containing the desired year-page URLs.
        '''
        logger.info(F'FETCHING root page {site_root}')
        urls = cls.fetch_page_href_urls(page_url=site_root)
        year_urls = set()
        for url in sorted(urls):
            if not url.startswith(site_root):
                continue
            relative_url = url[len(site_root):]
            rem = re.match(r'^\/?(?P<year>\d{4})\/', relative_url)
            if not rem:
                continue
            if int(rem.group('year')) < start_date.year:
                logger.debug(F'Not crawling into {relative_url} because it is before {start_date.isoformat()}')
                continue
            year_urls.add(url)
        return(year_urls)

    @classmethod
    def fetch_page_href_urls(cls, page_url:str) -> set:
        'Fetch page_url, parse it, and return a set of all the a-tag href attributes found on the page.'
        res = requests.get(url=page_url)
        res.raise_for_status()
        parser = MyHTMLParser(page_url=page_url)
        parser.feed(res.text)
        return parser.href_urls

    @classmethod
    def aws_lambda_entry_point(cls, event, context):
        '''
        TODO: Move this to AWS Lambda wrapper for use everywhere.
        TODO: CORS options.
        TODO: Web requests & return values w/ exception handling.
        '''
        logging.basicConfig(level='INFO')
        args = {}
        sig = inspect.signature(cls.wrapped_entry_point)
        if 'job_deadline' in sig.parameters:
            args['job_deadline'] = datetime.utcnow() + timedelta(milliseconds=context.get_remaining_time_in_millis())
        for pname, param in sig.parameters:
            if param.default == Parameter.empty:
                # required
                pass
            if param.annotation == Parameter.empty:
                pass
            elif param.annotation in [list, set]:
                raise NotImplemented('Need to convert input to list or set')
            penv = os.getenv(pname)
            if penv != None:
                args[pname] = penv
        wrapped_retval = cls.wrapped_entry_point(**args)
        return wrapped_retval

    @classmethod
    def cli_entry_point(cls):
        realtime_initial = datetime.utcnow()
        logging.basicConfig(
            level='INFO',
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
        ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
        ap.add_argument('--debug', action='store_true', help='Break into pdb after parsing arguments')
        ap.add_argument('--s3-snapshot-bucket-name', help='S3 bucket for uploading RPKI TAR files')
        ap.add_argument('--s3-snapshot-summary-bucket-name', help='S3 bucket containing JSON summary files')
        ap.add_argument('--site-root', help='Root of web archive site')
        ap.add_argument('--start-date', type=dateutil.parser.parse, help='Do not download snapshots earlier than this date')
        ap.add_argument('--job-max-runtime', type=float, help='Max runtime in seconds (default: unlimited)')
        ap.add_argument('--job-max-downloads', default=2, type=int, help='Max files to download before stopping (default: 2)')
        args = vars(ap.parse_args())
        if 'job_max_runtime' in args:
            args['job_deadline'] = datetime.utcnow() + timedelta(seconds=args['job_max_runtime'])
            args.pop('job_max_runtime')
        if 'debug' in args:
            args.pop('debug')
            import pdb
            pdb.set_trace()
        wrapped_retval = cls.wrapped_entry_point(**args)
        print(json.dumps(wrapped_retval, indent=4))
        times = os.times()
        realtime_final = datetime.utcnow()
        realtime_elapsed = realtime_final - realtime_initial
        try:
            import psutil
            memory_use_rss_mb = psutil.Process().memory_info().rss / 1048576
            logger.info(F'RAM memory_use_rss_mb={memory_use_rss_mb:.0f}')
        except:
            logger.warning(F'Unable to invoke psutil.Process().memory_info() to get RAM use.')
        logger.info(F'TIMES usr={times.user} sys={times.system} realtime={realtime_elapsed.total_seconds()}')

    @classmethod
    def wrapped_entry_point(
        cls,
        s3_snapshot_bucket_name:str,
        s3_snapshot_summary_bucket_name:str,
        site_root:str,
        start_date:datetime=None,
        job_deadline:datetime=None,
        job_max_downloads:int=None,
    ):
        '''
        Invoked by other entry points, e.g. cli_entry_point, aws_lambda_entry_point

        Web-crawl the given site_root and find relevant RPKI archive TAR URLs in the HTML a-tags.
        Crawling will try to avoid requesting pages that list only TAR files before start_date.
        
        Get the list of already-downloaded RPKI TARs by listing the s3_snapshot_summary_bucket
        and comparing the date-based filenames, for example:
            snapshot_summary: 20211121T000709Z.json.bz2
            snapshot: rpki-20211121T000709Z.tgz

        Also get the list of recently-downloaded TARs from s3_snapshot_bucket, in case there are
        some to-be-processed TARs already there.

        In ascending date-based order, download any TAR files we haven't previously processed,
        except TAR files with a datetime-based filename before start_date.

        After downloading each TAR, upload it to the s3_snapshot_bucket_name.

        Extract relevant JSON summary from each TAR and upload that to the s3_snapshot_summary_bucket_name.

        Abort if a download fails, or if an upload fails, to avoid skipping any files.
        '''
        if start_date==None:
            start_date=datetime.utcnow() - timedelta(days=7)
        
        # list files in relevant s3 buckets
        # figure out what snapshots we already have (in either S3 bucket) based on datetime-like filenames
        logger.info('LISTING relevant s3 buckets')
        s3 = boto3.client('s3')
        already_have_by_datetime = dict()
        uploaded = list()

        snapshot_bucket = boto3.resource('s3').Bucket(s3_snapshot_bucket_name)
        snapshots = set()
        for buckobj in snapshot_bucket.objects.all():
            snapshots.add(buckobj.key)
            rem = re.search(r'^rpki-(?P<datetime>\d{8}T\d{6})Z\.', buckobj.key)
            if rem:
                already_have_by_datetime[rem.group('datetime')] = buckobj
            else:
                logger.warning('UNMATCHED key in snapshot bucket {snapshot_bucket} : {buckobj.key}')

        summary_bucket = boto3.resource('s3').Bucket(s3_snapshot_summary_bucket_name)
        summaries = set()
        for buckobj in summary_bucket.objects.all():
            summaries.add(buckobj.key)
            rem = re.search(r'^(?P<datetime>\d{8}T\d{6})Z.json', buckobj.key)
            if rem:
                already_have_by_datetime[rem.group('datetime')] = buckobj
            else:
                logger.warning('UNMATCHED key in summary bucket {summary_bucket} : {buckobj.key}')
        logger.info(F'LISTED {len(snapshots)} snapshots and {len(summaries)} summaires in S3 buckets.')

        # get the list of all rpki tar files, after start_date, from the specified rpki archive site
        archive_site_available_tar_file_urls = cls.fetch_tar_urls_from_archive_site(
            site_root=site_root,
            start_date=start_date,
        )
        logger.info(F'FETCHED {len(archive_site_available_tar_file_urls)} URLs after {start_date} from {site_root}')
        
        # Iterate over available rpki tar files.
        # Determine which ones we don't already have.  Download those from archive and re-upload to snapshot bucket.
        # Stop if we're within 60s of job_deadline (lambda runtime might be exhausted because the downloads are slow.)
        for available_tar_url in sorted(archive_site_available_tar_file_urls):
            rem = re.search(r'(?P<filename>rpki-(?P<datetime>\d{8}T\d{6})Z\.tgz)$', available_tar_url)
            if not rem:
                logger.warning(F'UNMATCHED available_tar_url {available_tar_url}')
                continue
            available_tar_datetimestr = rem.group('datetime')
            destination_filename = rem.group('filename')
            if available_tar_datetimestr in already_have_by_datetime:
                # we've previously downloaded this tar from the archive site
                continue
            # new tar we need from archive site
            if job_deadline!=None and job_deadline < datetime.utcnow():
                # We're past the deadline.  Could run out of lambda execution time.  Stop here.
                logger.warn(F'JOB_DEADLINE reached.')
                break
            if job_max_downloads!=None and job_max_downloads <= len(uploaded):
                logger.warn(F'JOB_MAX_DOWNLOADS reached.')
                break

            logger.info(F'DOWNLOADING {available_tar_url}')
            retrieved_filename, retrieved_headers = urllib.request.urlretrieve(
                url=available_tar_url,
            )
            logger.info(F'UPLOADING {retrieved_filename} to {s3_snapshot_bucket_name}')
            s3.upload_file(
                Filename=str(retrieved_filename),
                Bucket=s3_snapshot_bucket_name,
                Key=destination_filename,
            )
            uploaded.append(destination_filename)
            logger.info(F'EXTRACTING useful summary file from tar')
            json_file_path = cls.extract_matching_file_from_tar(
                input_tar=retrieved_filename,
                output_dir=Path('/tmp'),
            )
            os.remove(retrieved_filename)
            logger.info(F'UPLOADING extracted file {json_file_path.name} to {s3_snapshot_summary_bucket_name}')
            s3.upload_file(
                Filename=str(json_file_path),
                Bucket=s3_snapshot_summary_bucket_name,
                Key=json_file_path.name,
            )
            os.remove(json_file_path)

        return uploaded
