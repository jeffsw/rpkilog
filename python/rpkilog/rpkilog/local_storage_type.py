from enum import Enum


class LocalStorageType(Enum):
    UNSPECIFIED = 0
    """No local-cache state has been established yet (freshly constructed)."""

    UNCACHED = 1
    """No local copy exists; the bytes live only in S3 and must be downloaded to use."""

    UNCOMPRESSED = 2
    """A locally-cached plain (uncompressed) JSON file at local_filepath_uncompressed."""

    BZIP2 = 3
    """A locally-cached bzip2-compressed JSON file at local_filepath_bz2."""

    SNAPSHOT_TGZ = 4
    """A locally-cached gzipped RPKI archive TAR (rpki-...Z.tgz) at local_filepath_tgz.

    Opaque binary blob, NOT a JSON document: it is uploaded/downloaded byte-for-byte and is never
    bz2-recompressed or JSON-parsed.  Used only by SnapshotFile.
    """
