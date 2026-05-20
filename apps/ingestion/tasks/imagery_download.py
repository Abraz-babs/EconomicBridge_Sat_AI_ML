"""Stream one Sentinel SAFE bundle from CDSE to tenant-prefixed S3.

Lifecycle per call, all in one DB transaction-per-step:

  1. INSERT public.imagery_downloads row (status='in_progress').
  2. Resolve scene_id → OData UUID via CDSE.
  3. Stream the SAFE bundle from CDSE's $value endpoint.
  4. While streaming, compute SHA-256 + track bytes.
  5. boto3 multipart-upload into s3://<bucket>/<tenant>/<collection>/...
     (or short-circuit to 'mocked' status when no bucket is configured).
  6. UPDATE imagery_downloads with status='succeeded' + size + sha + key.
  7. On any exception in 2-5: UPDATE the row with status='failed' +
     error_message and surface the original error to the caller.

The chunk loop buffers in memory to a SpooledTemporaryFile bounded to
roughly the configured part size — boto3's upload_fileobj needs a
seekable stream for multipart. For Sentinel scenes this means ≤ 8 MB
held in RAM at a time (settings.s3_imagery_part_size_bytes).
"""
from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db import is_valid_tenant_id
from sources.copernicus import CopernicusClient, CopernicusError
from sources.s3_client import (
    ImageryS3Client,
    S3Error,
    S3UploadResult,
    build_imagery_key,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImageryDownloadResult:
    """Summary returned to the caller / surfaced over HTTP."""

    download_id: UUID
    tenant_id: str
    scene_id: str
    collection: str
    status: str                       # in_progress | succeeded | failed | mocked
    s3_bucket: str
    s3_key: str
    size_bytes: int
    sha256: str | None
    duration_ms: int
    error_message: str | None


# ─── DB rows ───────────────────────────────────────────────────────────────


async def _existing_download(
    session: AsyncSession, *, tenant_id: str, scene_id: str
) -> dict[str, object] | None:
    """Return the catalogue row if this (tenant, scene) has already been
    archived. Lets the caller skip-and-return idempotently."""
    row = (
        await session.execute(
            text(
                """
                SELECT id, status, s3_bucket, s3_key, size_bytes, sha256,
                       download_completed_at, error_message
                  FROM public.imagery_downloads
                 WHERE tenant_id = :tenant AND scene_id = :scene
                """
            ),
            {"tenant": tenant_id, "scene": scene_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _insert_in_progress(
    session: AsyncSession,
    *,
    download_id: UUID,
    tenant_id: str,
    scene_id: str,
    collection: str,
    s3_bucket: str,
    s3_key: str,
    captured_at: datetime | None,
    trace_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.imagery_downloads (
                id, tenant_id, scene_id, collection,
                s3_bucket, s3_key, captured_at,
                status, trace_id
            ) VALUES (
                :id, :tenant_id, :scene_id, :collection,
                :s3_bucket, :s3_key, :captured_at,
                'in_progress', :trace_id
            )
            """
        ),
        {
            "id": download_id,
            "tenant_id": tenant_id,
            "scene_id": scene_id,
            "collection": collection,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "captured_at": captured_at,
            "trace_id": trace_id,
        },
    )


async def _finalise_succeeded(
    session: AsyncSession,
    *,
    download_id: UUID,
    size_bytes: int,
    sha256: str,
    mocked: bool,
) -> None:
    await session.execute(
        text(
            """
            UPDATE public.imagery_downloads
               SET status = :status,
                   size_bytes = :size,
                   sha256 = :sha,
                   download_completed_at = NOW()
             WHERE id = :id
            """
        ),
        {
            "id": download_id,
            "status": "mocked" if mocked else "succeeded",
            "size": int(size_bytes),
            "sha": sha256,
        },
    )


async def _finalise_failed(
    session: AsyncSession,
    *,
    download_id: UUID,
    error_message: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE public.imagery_downloads
               SET status = 'failed',
                   error_message = :err,
                   download_completed_at = NOW()
             WHERE id = :id
            """
        ),
        {"id": download_id, "err": error_message[:1000]},
    )


# ─── Streaming + hashing ──────────────────────────────────────────────────


def _spooled_buffer() -> tempfile.SpooledTemporaryFile:
    """Disk-backed buffer for the streamed body so boto3's upload_fileobj
    sees a seekable stream. Falls back to disk once the in-memory roll
    threshold is exceeded — keeps RAM bounded for huge SAFE bundles."""
    settings = get_settings()
    return tempfile.SpooledTemporaryFile(
        max_size=settings.s3_imagery_part_size_bytes * 2,
        mode="w+b",
    )


async def _stream_to_buffer(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> tuple[tempfile.SpooledTemporaryFile, int, str]:
    """Drain `response` into a spooled file. Returns (file, size, sha256).

    Raises ValueError if the body exceeds `max_bytes`.
    """
    buf = _spooled_buffer()
    hasher = hashlib.sha256()
    total = 0
    try:
        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(
                    f"Download exceeded max_bytes={max_bytes} "
                    f"(stopped at {total} bytes)"
                )
            buf.write(chunk)
            hasher.update(chunk)
    finally:
        await response.aclose()
    buf.seek(0)
    return buf, total, hasher.hexdigest()


# ─── Top-level entry point ────────────────────────────────────────────────


async def download_scene_to_s3(
    session: AsyncSession,
    *,
    tenant_id: str,
    scene_id: str,
    collection: str,
    captured_at: datetime,
    cdse_client: CopernicusClient | None = None,
    s3: ImageryS3Client | None = None,
    trace_id: UUID | None = None,
) -> ImageryDownloadResult:
    """Idempotent: same (tenant, scene) returns the existing row instead
    of re-downloading.
    """
    if not is_valid_tenant_id(tenant_id):
        raise ValueError(f"Unknown tenant_id: {tenant_id!r}")

    settings = get_settings()
    trace = trace_id or uuid4()
    started_ms = time.monotonic()

    # Short-circuit: already archived.
    existing = await _existing_download(
        session, tenant_id=tenant_id, scene_id=scene_id
    )
    if existing and existing.get("status") in ("succeeded", "mocked"):
        log.info(
            "imagery.download skip tenant=%s scene=%s already archived (id=%s)",
            tenant_id, scene_id, existing["id"],
        )
        return ImageryDownloadResult(
            download_id=existing["id"],
            tenant_id=tenant_id,
            scene_id=scene_id,
            collection=collection,
            status=str(existing["status"]),
            s3_bucket=str(existing["s3_bucket"]),
            s3_key=str(existing["s3_key"]),
            size_bytes=int(existing.get("size_bytes") or 0),
            sha256=(
                str(existing["sha256"]) if existing.get("sha256") else None
            ),
            duration_ms=0,
            error_message=None,
        )

    s3 = s3 if s3 is not None else ImageryS3Client()
    cdse = cdse_client if cdse_client is not None else CopernicusClient()

    bucket = s3.bucket if s3.configured else "<mock>"
    key = build_imagery_key(
        tenant_id=tenant_id,
        collection=collection,
        captured_at=captured_at,
        scene_id=scene_id,
    )

    download_id = uuid4()
    await _insert_in_progress(
        session,
        download_id=download_id,
        tenant_id=tenant_id,
        scene_id=scene_id,
        collection=collection,
        s3_bucket=bucket,
        s3_key=key,
        captured_at=captured_at,
        trace_id=trace,
    )
    await session.commit()

    # ── Work happens here ──────────────────────────────────────────────
    try:
        uuid_str = await cdse.lookup_scene_uuid(scene_id)
        if uuid_str is None:
            raise CopernicusError(f"Scene not found in CDSE OData: {scene_id!r}")

        response = await cdse.stream_download(scene_uuid=uuid_str)
        buf, total, sha = await _stream_to_buffer(
            response, max_bytes=settings.s3_imagery_max_bytes
        )
        try:
            upload: S3UploadResult = await s3.upload_stream(
                body=buf,
                key=key,
                content_length=total,
                sha256=sha,
            )
        finally:
            buf.close()

    except (CopernicusError, S3Error, ValueError, httpx.HTTPError) as exc:
        await _finalise_failed(
            session, download_id=download_id, error_message=str(exc)
        )
        await session.commit()
        log.exception(
            "imagery.download FAILED tenant=%s scene=%s: %s",
            tenant_id, scene_id, exc,
        )
        return ImageryDownloadResult(
            download_id=download_id,
            tenant_id=tenant_id,
            scene_id=scene_id,
            collection=collection,
            status="failed",
            s3_bucket=bucket,
            s3_key=key,
            size_bytes=0,
            sha256=None,
            duration_ms=int((time.monotonic() - started_ms) * 1000),
            error_message=str(exc),
        )

    await _finalise_succeeded(
        session,
        download_id=download_id,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256 or sha,
        mocked=upload.mocked,
    )
    await session.commit()

    duration_ms = int((time.monotonic() - started_ms) * 1000)
    log.info(
        "imagery.download OK tenant=%s scene=%s key=s3://%s/%s size=%s ms=%d mocked=%s",
        tenant_id, scene_id, upload.bucket, upload.key,
        upload.size_bytes, duration_ms, upload.mocked,
    )
    return ImageryDownloadResult(
        download_id=download_id,
        tenant_id=tenant_id,
        scene_id=scene_id,
        collection=collection,
        status="mocked" if upload.mocked else "succeeded",
        s3_bucket=upload.bucket,
        s3_key=upload.key,
        size_bytes=upload.size_bytes,
        sha256=upload.sha256 or sha,
        duration_ms=duration_ms,
        error_message=None,
    )
