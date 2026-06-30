"""Schemas for GET /api/v1/provenance — the data-source provenance catalog.

The "where is this data from / how genuine / is it OK to commercialise" answer
as a structured payload: every module's satellite source, product, provider,
licence + attribution, whether it is live or modelled, and its refresh cadence.
Plus the CDSE compute budget. Static truth — no per-tenant DB coupling.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DataKind = Literal["live", "modelled", "derived"]


class FeedProvenance(BaseModel):
    """Provenance of one module's data feed."""

    module: str
    signal: str
    satellites: list[str] = Field(default_factory=list)
    provider: str
    license: str            # plain-language licence + commercial status
    attribution: str        # the exact attribution string to display
    kind: DataKind          # live (real satellite/API) | modelled | derived
    cadence: str            # how often it refreshes
    method: str             # how we read it


class ComputeBudget(BaseModel):
    """The satellite-compute account the live feeds draw from."""

    provider: str
    tier: str
    monthly_pu: int
    monthly_requests: int
    note: str


class ProvenanceData(BaseModel):
    feeds: list[FeedProvenance] = Field(default_factory=list)
    compute: ComputeBudget
    summary: str
