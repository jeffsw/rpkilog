from enum import StrEnum


class CleanupPolicy(StrEnum):
    CLEANUP_ALWAYS = 'always'
    """Always unlink the local cache on destroy/exit."""

    CLEANUP_NEVER = 'never'
    """Never unlink the local cache (e.g. pointing at an externally owned source file)."""

    CLEANUP_IF_IN_S3 = 'if_in_s3'
    """Unlink the local cache only when s3_stored is True (default)."""
