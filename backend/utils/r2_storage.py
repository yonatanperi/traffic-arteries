"""Cloudflare R2 (S3-compatible) JSON object store.

The route/graph JSON that used to live on the local filesystem now lives as
objects in an R2 bucket, so the backend can run on Render's ephemeral
filesystem. boto3's S3 client speaks R2's S3-compatible API unchanged; the only
R2 specifics are the endpoint URL (built from the account id) and region
``"auto"``.

Configuration comes entirely from the environment, read lazily (per call) so
importing this module never requires R2 to be configured and so tests can wrap
operations in an in-process S3 mock:

  * ``R2_ACCOUNT_ID`` — subdomain of the R2 endpoint.
  * ``R2_ACCESS_KEY_ID`` / ``R2_SECRET_ACCESS_KEY`` — S3 API token.
  * ``R2_BUCKET_NAME`` — the bucket every key lives in.
  * ``R2_ENDPOINT_URL`` — *optional* full endpoint override; when unset it's
    derived from the account id. Tests point this at an S3-compatible mock.
"""

import json
import os

import boto3
from botocore.exceptions import ClientError

# S3 error codes that mean "the key isn't there" across get/head operations.
_MISSING_CODES = {"NoSuchKey", "NoSuchBucket", "404", "NotFound"}


class ObjectNotFound(KeyError):
    """Raised when a requested R2 object key does not exist."""


def _client():
    """A fresh boto3 S3 client pointed at R2.

    Built per call (not cached at import) so credentials are read lazily and so
    a test's S3 mock — which patches botocore — intercepts the client.
    """
    endpoint_url = os.environ.get("R2_ENDPOINT_URL") or (
        f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _bucket():
    return os.environ["R2_BUCKET_NAME"]


def download_json(key):
    """Return the object stored at ``key`` parsed from JSON.

    Raises :class:`ObjectNotFound` if the key doesn't exist.
    """
    try:
        response = _client().get_object(Bucket=_bucket(), Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in _MISSING_CODES:
            raise ObjectNotFound(key) from exc
        raise
    return json.loads(response["Body"].read().decode("utf-8"))


def upload_json(key, data):
    """Serialize ``data`` to JSON and store it at ``key``.

    ``PutObject`` is atomic per key, so there's no temp-file/rename dance the
    old filesystem store needed. ``ensure_ascii=False`` keeps the Hebrew place
    names readable in the stored object.
    """
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _client().put_object(
        Bucket=_bucket(), Key=key, Body=body, ContentType="application/json"
    )


def object_exists(key):
    """Whether an object exists at ``key``."""
    try:
        _client().head_object(Bucket=_bucket(), Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in _MISSING_CODES:
            return False
        raise
    return True
