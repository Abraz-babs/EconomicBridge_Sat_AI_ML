"""Schemas for the reports endpoints (generic across modules)."""
from __future__ import annotations

from pydantic import BaseModel


class ReportMetric(BaseModel):
    label: str
    display: str


class ReportBreakdownRow(BaseModel):
    key: str
    count: int


class ReportBreakdown(BaseModel):
    title: str
    rows: list[ReportBreakdownRow]


class ReportSummary(BaseModel):
    module: str
    label: str
    date_from: str
    date_to: str
    total_rows: int
    metrics: list[ReportMetric]
    breakdown: ReportBreakdown | None = None


class ReportModuleInfo(BaseModel):
    """A reportable module (for the frontend's module picker)."""
    key: str
    label: str
