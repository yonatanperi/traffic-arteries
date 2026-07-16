"""JSON object store with two interchangeable, class-based backends.

The route/graph JSON is addressed by opaque string *keys* (``routes.json``,
``edge_routes.json``, ``compromised.json``, optionally namespaced by a prefix).
Two backends implement the same :class:`JsonObjectStore` interface:

  * :class:`R2Storage` — Cloudflare R2 (S3-compatible). boto3's S3 client speaks
    R2's API unchanged; the only R2 specifics are the endpoint URL (built from the
    account id) and region ``"auto"``. This is what lets the backend run on
    Render's ephemeral filesystem.
  * :class:`LocalFileStore` — the fallback when R2 is *not* configured, so a plain
    ``git clone`` + ``runserver`` still works offline with no cloud credentials.
    Keys map to files under ``LOCAL_DATA_DIR`` (default ``backend/data``); writes
    are atomic (temp file + ``os.replace``), matching the pre-R2 behaviour.

:class:`Storage` is the facade the app uses: it picks the active backend *per
call* from the environment, so nothing is baked in at import time — env changes
(and a test's mocked env) take effect immediately. The module-level
:data:`storage` singleton is the shared instance.

Configuration (read lazily, per call):

  * ``R2_ACCOUNT_ID`` — subdomain of the R2 endpoint.
  * ``R2_ACCESS_KEY_ID`` / ``R2_SECRET_ACCESS_KEY`` — S3 API token.
  * ``R2_BUCKET_NAME`` — the bucket every key lives in.
  * ``R2_ENDPOINT_URL`` — *optional* full endpoint override; when unset it's
    derived from the account id. Tests point this at an S3-compatible mock.
  * ``LOCAL_DATA_DIR`` — *optional* root for the local fallback (default
    ``backend/data``).

R2 is used only when the credentials, a bucket, and an endpoint (either
``R2_ENDPOINT_URL`` or ``R2_ACCOUNT_ID``) are all present; otherwise the local
filesystem backend is used.
"""

import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# S3 error codes that mean "the key isn't there" across get/head operations.
_MISSING_CODES = {"NoSuchKey", "NoSuchBucket", "404", "NotFound"}

# Where the local-filesystem fallback keeps its objects by default. This file is
# ``backend/utils/r2_storage.py``, so this resolves to ``backend/data``.
_DEFAULT_LOCAL_DIR = Path(__file__).resolve().parent.parent / "data"


class ObjectNotFound(KeyError):
    """Raised when a requested object key does not exist."""


class JsonObjectStore:
    """Interface for a keyed JSON object store.

    Backends store/fetch JSON values addressed by opaque string keys. Keys may be
    ``/``-separated to namespace objects (the local backend mirrors that on disk;
    R2 treats it as a flat key).
    """

    def download_json(self, key):
        """Return the object at ``key`` parsed from JSON, or raise
        :class:`ObjectNotFound`."""
        raise NotImplementedError

    def upload_json(self, key, data):
        """Serialize ``data`` to JSON and store it atomically at ``key``."""
        raise NotImplementedError

    def object_exists(self, key):
        """Whether an object exists at ``key``."""
        raise NotImplementedError


class R2Storage(JsonObjectStore):
    """:class:`JsonObjectStore` backed by a Cloudflare R2 (S3) bucket.

    Credentials, bucket, and endpoint are read from the environment on every
    operation, so a fresh boto3 client is built per call — nothing is cached at
    construction, which keeps a test's S3 mock (patching botocore) effective.
    """

    @staticmethod
    def is_configured():
        """Whether the environment fully configures R2 (else it can't be used)."""
        has_endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("R2_ACCOUNT_ID")
        return bool(
            has_endpoint
            and os.environ.get("R2_ACCESS_KEY_ID")
            and os.environ.get("R2_SECRET_ACCESS_KEY")
            and os.environ.get("R2_BUCKET_NAME")
        )

    def _client(self):
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

    def _bucket(self):
        return os.environ["R2_BUCKET_NAME"]

    def download_json(self, key):
        try:
            response = self._client().get_object(Bucket=self._bucket(), Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in _MISSING_CODES:
                raise ObjectNotFound(key) from exc
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def upload_json(self, key, data):
        # PutObject is atomic per key, so no temp-file/rename dance is needed.
        # ensure_ascii=False keeps the Hebrew place names readable in the object.
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._client().put_object(
            Bucket=self._bucket(), Key=key, Body=body, ContentType="application/json"
        )

    def object_exists(self, key):
        try:
            self._client().head_object(Bucket=self._bucket(), Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in _MISSING_CODES:
                return False
            raise
        return True


class LocalFileStore(JsonObjectStore):
    """:class:`JsonObjectStore` backed by JSON files under a local directory.

    The pre-R2 store: keys map to files under ``root`` (default: ``LOCAL_DATA_DIR``
    or ``backend/data``). ``root`` is resolved per call so an env change is picked
    up unless an explicit root was passed to the constructor.
    """

    def __init__(self, root=None):
        self._explicit_root = Path(root) if root is not None else None

    def _root(self):
        if self._explicit_root is not None:
            return self._explicit_root
        return Path(os.environ.get("LOCAL_DATA_DIR") or _DEFAULT_LOCAL_DIR)

    def _path(self, key):
        # Keys may be prefixed (``prefix/routes.json``); mirror that under root.
        return self._root() / key

    def download_json(self, key):
        try:
            text = self._path(key).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc
        return json.loads(text)

    def upload_json(self, key, data):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(data, ensure_ascii=False, indent=2)
        # Atomic: write a sibling temp file, then replace — a reader never sees a
        # half-written object (the guarantee R2's PutObject gives per key).
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)

    def object_exists(self, key):
        return self._path(key).exists()


class Storage(JsonObjectStore):
    """Facade that dispatches each operation to R2 or the local filesystem.

    The choice is made per call via :meth:`R2Storage.is_configured`, so the same
    instance transparently follows the environment (cloud in production, on-disk
    locally).
    """

    def __init__(self, r2=None, local=None):
        self._r2 = r2 if r2 is not None else R2Storage()
        self._local = local if local is not None else LocalFileStore()

    def _backend(self):
        return self._r2 if R2Storage.is_configured() else self._local

    def download_json(self, key):
        return self._backend().download_json(key)

    def upload_json(self, key, data):
        self._backend().upload_json(key, data)

    def object_exists(self, key):
        return self._backend().object_exists(key)


# The shared instance the app uses.
storage = Storage()
