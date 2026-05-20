"""Tests for sources/s3_client.py — key construction + mock/real upload paths.

The "real" path is tested against moto's in-memory S3 stub. CLAUDE.md §11
forbids real AWS calls in tests.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from config import get_settings
from sources.s3_client import (
    ImageryS3Client,
    S3Error,
    build_imagery_key,
)


# ─── Key construction ──────────────────────────────────────────────────────


def test_build_imagery_key_uses_tenant_collection_yyyy_mm_dd_layout():
    key = build_imagery_key(
        tenant_id="kebbi",
        collection="sentinel-2-l2a",
        captured_at=datetime(2026, 5, 19, 10, 28, tzinfo=timezone.utc),
        scene_id="S2A_MSIL2A_20260519T102601",
    )
    assert key == "kebbi/sentinel-2-l2a/2026/05/19/S2A_MSIL2A_20260519T102601.zip"


def test_build_imagery_key_pads_single_digit_month_day():
    key = build_imagery_key(
        tenant_id="benue",
        collection="sentinel-1-grd",
        captured_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        scene_id="S1A_X",
    )
    assert "/2026/01/03/" in key


def test_build_imagery_key_rejects_empty_tenant():
    with pytest.raises(ValueError, match="tenant_id is required"):
        build_imagery_key(
            tenant_id="",
            collection="sentinel-2-l2a",
            captured_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
            scene_id="X",
        )


def test_build_imagery_key_strips_trailing_slash_from_scene():
    key = build_imagery_key(
        tenant_id="kebbi",
        collection="sentinel-2-l2a",
        captured_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        scene_id="S2A_X/",
    )
    assert key.endswith("/S2A_X.zip")


def test_build_imagery_key_accepts_custom_suffix():
    key = build_imagery_key(
        tenant_id="kebbi",
        collection="sentinel-2-l2a",
        captured_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        scene_id="S2A_X",
        suffix=".SAFE.zip",
    )
    assert key.endswith(".SAFE.zip")


# ─── Mock mode (no bucket configured) ──────────────────────────────────────


@pytest.fixture
def unconfigured_s3(monkeypatch):
    monkeypatch.setenv("S3_IMAGERY_BUCKET", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_client_configured_false_when_bucket_empty(unconfigured_s3):
    assert ImageryS3Client().configured is False


@pytest.mark.asyncio
async def test_upload_stream_returns_mocked_when_unconfigured(unconfigured_s3):
    client = ImageryS3Client()
    body = io.BytesIO(b"fake-safe-payload")
    result = await client.upload_stream(
        body=body,
        key="kebbi/sentinel-2-l2a/2026/05/19/X.zip",
        content_length=17,
        sha256="abc123",
    )
    assert result.mocked is True
    assert result.bucket == "<mock>"
    assert result.key == "kebbi/sentinel-2-l2a/2026/05/19/X.zip"
    assert result.size_bytes == 17
    assert result.sha256 == "abc123"


@pytest.mark.asyncio
async def test_head_object_returns_none_in_mock_mode(unconfigured_s3):
    assert await ImageryS3Client().head_object(key="anything") is None


# ─── Real mode (moto-backed) ───────────────────────────────────────────────


@pytest.fixture
def configured_s3(monkeypatch):
    monkeypatch.setenv("S3_IMAGERY_BUCKET", "eb-test-bucket")
    monkeypatch.setenv("S3_IMAGERY_REGION", "us-east-1")
    # moto needs *some* AWS env so boto3 doesn't try IAM/profile resolution.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_upload_stream_real_mode_with_moto(configured_s3):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="eb-test-bucket")

        client = ImageryS3Client(s3=s3)
        body = io.BytesIO(b"\x00" * 1024)  # 1 KB of zeros
        result = await client.upload_stream(
            body=body,
            key="kebbi/sentinel-2-l2a/2026/05/19/X.zip",
            content_length=1024,
            sha256="zerosha",
        )
        assert result.mocked is False
        assert result.bucket == "eb-test-bucket"

        # Object actually present in moto's S3.
        head = s3.head_object(
            Bucket="eb-test-bucket",
            Key="kebbi/sentinel-2-l2a/2026/05/19/X.zip",
        )
        assert head["ContentLength"] == 1024
        # Custom metadata round-trips (boto lowercases the key).
        assert head["Metadata"].get("sha256") == "zerosha"


@pytest.mark.asyncio
async def test_head_object_returns_none_when_object_missing(configured_s3):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="eb-test-bucket")
        client = ImageryS3Client(s3=s3)
        assert await client.head_object(key="no-such-key") is None


@pytest.mark.asyncio
async def test_head_object_returns_metadata_when_present(configured_s3):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="eb-test-bucket")
        s3.put_object(Bucket="eb-test-bucket", Key="x", Body=b"hi")
        client = ImageryS3Client(s3=s3)
        meta = await client.head_object(key="x")
        assert meta is not None
        assert meta["ContentLength"] == 2


@pytest.mark.asyncio
async def test_upload_stream_surfaces_botocore_errors_as_s3error(configured_s3):
    with mock_aws():
        # No create_bucket call — uploads to a missing bucket raise.
        s3 = boto3.client("s3", region_name="us-east-1")
        client = ImageryS3Client(s3=s3)
        with pytest.raises(S3Error):
            await client.upload_stream(
                body=io.BytesIO(b"x"),
                key="k",
                content_length=1,
            )
