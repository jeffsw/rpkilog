"""
Tests for archive_site_crawler leaf functions: TAR-URL derivation and index-page parsing.

The network/orchestration paths (download_tar, process_tar_url, wrapped_entry_point) are
deliberately untested here: they would need requests + S3 + tarfile fakes stacked together,
coupling tests to implementation structure rather than behavior.  TAR content handling is
covered in test_snapshot_file.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from rpkilog.archive_site_crawler import ArchiveSiteCrawler, MyHTMLParser, parse_interval

JOSEPHINE_BASE = 'https://josephine.sobornost.net/rpkidata/'
JOSEPHINE_TAR_URL = 'https://josephine.sobornost.net/rpkidata/2026/05/01/rpki-20260501T005438Z.tgz'
TAR_DT = datetime(2026, 5, 1, 0, 54, 38, tzinfo=timezone.utc)


# --- derive_tar_url ---

def test_derive_tar_url_josephine_example():
    url = ArchiveSiteCrawler.derive_tar_url(base_url=JOSEPHINE_BASE, datetimestamp=TAR_DT)
    assert url == JOSEPHINE_TAR_URL


def test_derive_tar_url_adds_missing_trailing_slash():
    url = ArchiveSiteCrawler.derive_tar_url(base_url=JOSEPHINE_BASE.rstrip('/'), datetimestamp=TAR_DT)
    assert url == JOSEPHINE_TAR_URL


def test_derive_tar_url_naive_datetimestamp_assumed_utc():
    url = ArchiveSiteCrawler.derive_tar_url(
        base_url=JOSEPHINE_BASE,
        datetimestamp=TAR_DT.replace(tzinfo=None),
    )
    assert url == JOSEPHINE_TAR_URL


def test_derive_tar_url_converts_nonutc_timezone():
    plus2 = TAR_DT.astimezone(timezone(timedelta(hours=2)))
    url = ArchiveSiteCrawler.derive_tar_url(base_url=JOSEPHINE_BASE, datetimestamp=plus2)
    assert url == JOSEPHINE_TAR_URL


# --- MyHTMLParser ---

def test_parser_relative_and_absolute_hrefs():
    page_url = JOSEPHINE_BASE + '2026/05/01/'
    page = (
        '<html><body>'
        '<a href="rpki-20260501T005438Z.tgz">rpki-20260501T005438Z.tgz</a>'
        '<a href="https://example.net/absolute.tgz">absolute</a>'
        '<img src="notalink.png">'
        '<a name="anchor-without-href">no href</a>'
        '</body></html>'
    )
    parser = MyHTMLParser(page_url=page_url)
    parser.feed(page)
    assert parser.href_urls == {
        page_url + 'rpki-20260501T005438Z.tgz',
        'https://example.net/absolute.tgz',
    }


# --- round-trip invariant ---

def test_derived_url_matches_crawler_discovery_byte_for_byte():
    """
    archive_file dedups on source_url, so derive_tar_url() output must be byte-for-byte
    identical to what a crawl constructs for the same file: the day-page URL (site_root +
    %Y/%m/%d/, as in fetch_tar_urls_from_archive_site) plus the page's relative filename href
    (as resolved by MyHTMLParser).  Either side drifting fails this test.
    """
    day_page_url = JOSEPHINE_BASE + TAR_DT.strftime('%Y/%m/%d/')
    page = f'<a href="rpki-{TAR_DT.strftime("%Y%m%dT%H%M%SZ")}.tgz">link</a>'
    parser = MyHTMLParser(page_url=day_page_url)
    parser.feed(page)
    assert len(parser.href_urls) == 1
    discovered_url = parser.href_urls.pop()
    derived_url = ArchiveSiteCrawler.derive_tar_url(base_url=JOSEPHINE_BASE, datetimestamp=TAR_DT)
    assert derived_url == discovered_url


# --- parse_interval ---

def test_parse_interval_seconds():
    assert parse_interval('30s') == timedelta(seconds=30)


def test_parse_interval_minutes():
    assert parse_interval('5m') == timedelta(minutes=5)


def test_parse_interval_fractional_hours():
    assert parse_interval('1.5h') == timedelta(minutes=90)


def test_parse_interval_rejects_missing_unit():
    with pytest.raises(ValueError):
        parse_interval('30')
