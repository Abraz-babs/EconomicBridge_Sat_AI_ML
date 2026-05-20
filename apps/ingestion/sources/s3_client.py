"""Async-friendly S3 wrapper for the imagery archive.

boto3 is synchronous. We wrap the I/O-bound calls in `asyncio.to_thread`
so the FastAPI event loop stays responsive during long multipart uploads.

Mock mode (when `s3_imagery_bucket` is empty) returns deterministic
results without ever calling AWS — useful for tests and dev machines
without AWS credentials configured. The downloader records what *would*
have been uploaded so the imagery_downloads table still gets a row
(status='mocked').

Key layout (CLAUDE.md §4.2: S3 keys ALWAYS prefixed with tenant_id):
    s3://<bucket>/<tenant_id>/<collection>/<YYYY>/<MM>/<DD>/<scene_id>.zip

Why slot the date into the key path: cheap listing / lifecycle policies
("delete all > 365 days") become a single prefix scan instead of a full
table query.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import IO, Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class S3UploadResult:
    """What the caller needs to know after the upload attempt."""

    bucket: str
    key: str
    size_bytes: int
    sha256: str | None
    mocked: bool


class S3Error(RuntimeError):
    """Wrap any AWS-side failure with our trace-friendly message."""


# ─── Key construction ────────────────────────────────────────────────────


def build_imagery_key(
    *,
    tenant_id: str,
    collection: str,
    captured_at: datetime,
    scene_id: str,
    suffix: str = ".zip",
) -> str:
    """Produce the canonical S3 key for one scene.

    `captured_at` is the satellite acquisition time, NOT the download time
    — so re-running the same download produces the same key (idempotency).
    """
    if not tenant_id:
        raise ValueError("tenant_id is required for S3 key construction")
    safe_scene = scene_id.rstrip("/")
    return (
        f"{tenant_id}/{collection}/"
        f"{captured_at.year:04d}/{captured_at.month:02d}/{captured_at.day:02d}/"
        f"{safe_scene}{suffix}"
    )


# ─── Client ───────────────────────────────────────────────────────────────


class ImageryS3Client:
    """Thin async-friendly wrapper around boto3 S3.

    Construct one per process; the underlying boto3 client is cached and
    thread-safe. Pass a pre-built boto3 client in `s3` for tests (lets
    moto's stubbed client flow through unchanged).
    """

    def __init__(self, *, s3: Any | None = None) -> None:
        self._settings = get_settings()
        self._s3 = s3
        self._client_cached = s3 is not None

    @property
    def configured(self) -> bool:
        return bool(self._settings.s3_imagery_bucket)

    @property
    def bucket(self) -> str:
        return self._settings.s3_imagery_bucket

    def _client(self) -> Any:
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3", region_name=self._settings.s3_imagery_region
            )
            self._client_cached = True
        return self._s3

    async def upload_stream(
        self,
        *,
        body: IO[bytes],
        key: str,
        content_length: int | None = None,
        content_type: str = "application/zip",
        sha256: str | None = None,
    ) -> S3UploadResult:
        """Upload an already-opened binary stream to S3.

        In mock mode (no bucket configured), short-circuits to a deterministic
        S3UploadResult with `mocked=True` and *does not consume the body*
        — the caller may close it on its own.
        """
        if not self.configured:
            log.info(
                "s3.upload (mock) key=%s content_length=%s — bucket not configured",
                key, content_length,
            )
            return S3UploadResult(
                bucket="<mock>",
                key=key,
                size_bytes=int(content_length or 0),
                sha256=sha256,
                mocked=True,
            )

        extra: dict[str, Any] = {"ContentType": content_type}
        if sha256 is not None:
            extra["Metadata"] = {"sha256": sha256}

        def _do_upload() -> None:
            client = self._client()
            # boto3's upload_fileobj handles multipart automatically when
            # the body is large. ExtraArgs sets headers + metadata.
            client.upload_fileobj(
                Fileobj=body,
                Bucket=self.bucket,
                Key=key,
                ExtraArgs=extra,
            )

        try:
            await asyncio.to_thread(_do_upload)
        except (BotoCoreError, ClientError) as exc:
            raise S3Error(f"S3 upload failed for key={key}: {exc}") from exc

        log.info("s3.upload OK bucket=%s key=%s size=%s", self.bucket, key, content_length)
        return S3UploadResult(
            bucket=self.bucket,
            key=key,
            size_bytes=int(content_length or 0),
            sha256=sha256,
            mocked=False,
        )

    async def head_object(self, *, key: str) -> dict[str, Any] | None:
        """Return basic metadata if the object exists, or None if it doesn't.

        Used by callers to skip re-uploading a scene we already have.
        Mock mode always returns None (every key is "new").
        """
        if not self.configured:
            return None

        def _do_head() -> dict[str, Any] | None:
            client = self._client()
            try:
                return client.head_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    return None
                raise

        try:
            return await asyncio.to_thread(_do_head)
        except (BotoCoreError, ClientError) as exc:
            raise S3Error(f"S3 head_object failed for key={key}: {exc}") from exc
