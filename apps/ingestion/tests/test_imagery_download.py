"""Integration tests for tasks/imagery_download.py.

Wires together: mocked CDSE OAuth + OData lookup + streaming download,
a moto-backed S3, and a real Postgres `imagery_downloads` row written
into the dev database. Everything heavy is mocked; the test exercises
the orchestration logic + DB writes.

Marked `integration` because they need a live Postgres on localhost:5434
with migrations applied (CLAUDE.md §11 — same convention as
test_firms_ingest / test_farmland_alerts). Run with `pytest -m integration`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import boto3
import httpx
import pytest
from moto import mock_aws
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from config import get_settings
from sources.copernicus import CopernicusClient
from sources.s3_client import ImageryS3Client
from tasks.imagery_download import download_scene_to_s3

pytestmark = pytest.mark.integration


# ─── Fixtures ──────────────────────────────────────────────────────────────


def _make_transport(*, scene_id: str, body: bytes) -> httpx.MockTransport:
    """One transport that answers OAuth + OData lookup + $value download.

    Routed by URL substring — each handler returns deterministic bytes.
    """
    uuid = "00000000-0000-0000-0000-000000000001"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openid-connect/token" in url:
            return httpx.Response(200, content=json.dumps({
                "access_token": "tok", "expires_in": 1800, "token_type": "Bearer",
            }).encode())
        if "/Products?" in url and "$filter" in url:
            return httpx.Response(200, content=json.dumps({
                "value": [{"Id": uuid, "Name": scene_id}],
            }).encode())
        if f"Products({uuid})/$value" in url:
            return httpx.Response(
                200,
                content=body,
                headers={"Content-Type": "application/octet-stream"},
            )
        return httpx.Response(404, content=b"unmocked")

    return httpx.MockTransport(handler)


@pytest.fixture
def env_setup(monkeypatch):
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "cid")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "csec")
    monkeypatch.setenv("S3_IMAGERY_BUCKET", "eb-test-bucket")
    monkeypatch.setenv("S3_IMAGERY_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def session():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    sessionmaker = __import__("sqlalchemy.ext.asyncio", fromlist=["async_sessionmaker"]).async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False,
    )
    async with sessionmaker() as s:
        # Clean test rows from prior runs.
        await s.execute(
            text(
                "DELETE FROM public.imagery_downloads WHERE scene_id LIKE 'TEST_%'"
            )
        )
        await s.commit()
        yield s
        await s.execute(
            text(
                "DELETE FROM public.imagery_downloads WHERE scene_id LIKE 'TEST_%'"
            )
        )
        await s.commit()
    await engine.dispose()


# ─── The tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_streams_body_to_moto_s3_and_records_row(env_setup, session):
    scene_id = "TEST_S2A_HAPPY"
    body = b"\xff" * 4096   # 4 KB payload

    with mock_aws():
        s3_native = boto3.client("s3", region_name="us-east-1")
        s3_native.create_bucket(Bucket="eb-test-bucket")
        s3 = ImageryS3Client(s3=s3_native)

        async with httpx.AsyncClient(
            transport=_make_transport(scene_id=scene_id, body=body)
        ) as http:
            cdse = CopernicusClient(http=http)
            result = await download_scene_to_s3(
                session,
                tenant_id="kebbi",
                scene_id=scene_id,
                collection="sentinel-2-l2a",
                captured_at=datetime(2026, 5, 19, 10, 28, tzinfo=timezone.utc),
                cdse_client=cdse,
                s3=s3,
            )

        assert result.status == "succeeded"
        assert result.size_bytes == 4096
        assert result.s3_bucket == "eb-test-bucket"
        assert result.s3_key.startswith("kebbi/sentinel-2-l2a/2026/05/19/")
        assert result.sha256 and len(result.sha256) == 64
        # Object actually landed in S3.
        head = s3_native.head_object(Bucket="eb-test-bucket", Key=result.s3_key)
        assert head["ContentLength"] == 4096

    # DB row recorded the final status.
    row = (await session.execute(
        text(
            "SELECT status, size_bytes, sha256 FROM public.imagery_downloads "
            "WHERE scene_id = :s"
        ),
        {"s": scene_id},
    )).mappings().first()
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["size_bytes"] == 4096


@pytest.mark.asyncio
async def test_download_idempotent_when_scene_already_archived(env_setup, session):
    scene_id = "TEST_S2A_IDEMPOTENT"
    body = b"\x01" * 1024

    with mock_aws():
        s3_native = boto3.client("s3", region_name="us-east-1")
        s3_native.create_bucket(Bucket="eb-test-bucket")
        s3 = ImageryS3Client(s3=s3_native)

        async with httpx.AsyncClient(
            transport=_make_transport(scene_id=scene_id, body=body)
        ) as http:
            cdse = CopernicusClient(http=http)
            captured = datetime(2026, 5, 19, 10, 28, tzinfo=timezone.utc)
            first = await download_scene_to_s3(
                session,
                tenant_id="kebbi",
                scene_id=scene_id,
                collection="sentinel-2-l2a",
                captured_at=captured,
                cdse_client=cdse,
                s3=s3,
            )
            second = await download_scene_to_s3(
                session,
                tenant_id="kebbi",
                scene_id=scene_id,
                collection="sentinel-2-l2a",
                captured_at=captured,
                cdse_client=cdse,
                s3=s3,
            )

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    # Same download id => second call short-circuited.
    assert first.download_id == second.download_id
    assert second.duration_ms == 0


@pytest.mark.asyncio
async def test_download_records_failed_when_scene_uuid_not_found(env_setup, session):
    scene_id = "TEST_S2A_MISSING"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openid-connect/token" in url:
            return httpx.Response(200, content=json.dumps({
                "access_token": "tok", "expires_in": 1800, "token_type": "Bearer",
            }).encode())
        if "/Products?" in url and "$filter" in url:
            return httpx.Response(200, content=json.dumps({"value": []}).encode())
        return httpx.Response(404, content=b"unexpected")

    transport = httpx.MockTransport(handler)
    with mock_aws():
        s3_native = boto3.client("s3", region_name="us-east-1")
        s3_native.create_bucket(Bucket="eb-test-bucket")
        s3 = ImageryS3Client(s3=s3_native)

        async with httpx.AsyncClient(transport=transport) as http:
            cdse = CopernicusClient(http=http)
            result = await download_scene_to_s3(
                session,
                tenant_id="kebbi",
                scene_id=scene_id,
                collection="sentinel-2-l2a",
                captured_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
                cdse_client=cdse,
                s3=s3,
            )

    assert result.status == "failed"
    assert result.error_message is not None
    assert "not found" in result.error_message.lower()

    row = (await session.execute(
        text(
            "SELECT status, error_message FROM public.imagery_downloads "
            "WHERE scene_id = :s"
        ),
        {"s": scene_id},
    )).mappings().first()
    assert row["status"] == "failed"
    assert row["error_message"]
