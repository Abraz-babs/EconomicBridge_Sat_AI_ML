"""Historical reports + export across all modules (summary / CSV / PDF).

Config-driven: each module maps to a ReportSpec (table, date column, export
columns, summary metrics, optional categorical breakdown). One set of endpoints
serves every module — add a module by adding a spec.

  GET /reports/modules                    — reportable modules (for the picker)
  GET /reports/summary?module=&from=&to=  — aggregated stats for the window
  GET /reports/export.csv?module=&from=&to= — CSV of the rows (opens in Excel)
  GET /reports/export.pdf?module=&from=&to= — formatted PDF summary

Reads the active tenant's per-tenant table via the pinned search_path
(X-Tenant-Id). TenantContextMiddleware enforces that the caller may view that
tenant, so exports are access-controlled. `from`/`to` are ISO dates (optional;
default last 365 days).
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from dependencies import CurrentUser, require_super_admin
from schemas.envelope import SuccessResponse, build_meta
from schemas.reports import (
    ReportBreakdown,
    ReportBreakdownRow,
    ReportMetric,
    ReportModuleInfo,
    ReportSubscription,
    ReportSubscriptionCreate,
    ReportSummary,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@dataclass(frozen=True)
class Metric:
    label: str
    agg: str               # 'rows' | 'sum' | 'avg' | 'distinct'
    column: str | None = None
    fmt: str = "int"       # 'int' | 'float1' | 'ngn' | 'pct'


@dataclass(frozen=True)
class ReportSpec:
    label: str
    table: str
    date_col: str
    columns: list[str]                      # CSV export columns
    metrics: list[Metric]
    breakdown_col: str | None = None
    breakdown_title: str | None = None


# Module key → report spec. Keys match the dashboard module/tab ids.
REPORT_SPECS: dict[str, ReportSpec] = {
    "farmland": ReportSpec(
        label="Farmland Protection", table="alert_events", date_col="created_at",
        columns=["created_at", "alert_type", "severity", "status", "lga", "zone_name",
                 "confidence_score", "affected_area_ha", "livelihoods_at_risk",
                 "economic_value_ngn", "predicted_breach_hours", "satellite_source",
                 "model_name", "model_version"],
        metrics=[
            Metric("Total alerts", "rows"),
            Metric("Livelihoods at risk", "sum", "livelihoods_at_risk"),
            Metric("Hectares affected", "sum", "affected_area_ha"),
            Metric("Economic value at risk", "sum", "economic_value_ngn", "ngn"),
        ],
        breakdown_col="severity", breakdown_title="By severity"),
    "economic-visibility": ReportSpec(
        label="Poverty Mapping", table="poverty_villages", date_col="created_at",
        columns=["created_at", "settlement_name", "lga", "poverty_score", "population",
                 "households_unreached", "nightlight_dimness", "viirs_pixel_radiance",
                 "worldpop_estimate", "source"],
        metrics=[
            Metric("Villages mapped", "rows"),
            Metric("Avg poverty score", "avg", "poverty_score", "float1"),
            Metric("Population covered", "sum", "population"),
            Metric("Households unreached", "sum", "households_unreached"),
        ]),
    "aid-coordination": ReportSpec(
        label="Aid Coordination", table="aid_coverage", date_col="created_at",
        columns=["created_at", "agency_slug", "lga", "beneficiaries_served",
                 "last_active_at", "source"],
        metrics=[
            Metric("Coverage records", "rows"),
            Metric("Beneficiaries served", "sum", "beneficiaries_served"),
            Metric("Agencies active", "distinct", "agency_slug"),
            Metric("LGAs covered", "distinct", "lga"),
        ]),
    "cropguard": ReportSpec(
        label="CropGuard", table="crop_predictions", date_col="created_at",
        columns=["created_at", "predicted_class", "confidence", "confidence_band",
                 "lga", "zone_name", "model_name", "model_version"],
        metrics=[
            Metric("Predictions", "rows"),
            Metric("Avg confidence", "avg", "confidence", "frac_pct"),
            Metric("Crop classes seen", "distinct", "predicted_class"),
            Metric("LGAs", "distinct", "lga"),
        ],
        breakdown_col="predicted_class", breakdown_title="By predicted class"),
    "shockguard": ReportSpec(
        label="ShockGuard", table="shock_events", date_col="created_at",
        columns=["created_at", "event_type", "severity", "confidence",
                 "projected_onset_hours", "affected_area_km2", "population_at_risk",
                 "lga", "zone_name", "source"],
        metrics=[
            Metric("Events", "rows"),
            Metric("Population at risk", "sum", "population_at_risk"),
            Metric("Area affected (km²)", "sum", "affected_area_km2", "float1"),
            Metric("LGAs", "distinct", "lga"),
        ],
        breakdown_col="event_type", breakdown_title="By event type"),
    "mobility-compass": ReportSpec(
        label="Mobility Compass", table="mobility_indicators", date_col="observed_at",
        columns=["observed_at", "lga", "cost_of_living_index", "avg_household_income_ngn",
                 "avg_household_income_usd", "income_opportunity_score", "population", "source"],
        metrics=[
            Metric("LGA observations", "rows"),
            Metric("Avg cost-of-living index", "avg", "cost_of_living_index", "float1"),
            Metric("Avg household income (₦)", "avg", "avg_household_income_ngn", "ngn"),
            Metric("Avg opportunity score", "avg", "income_opportunity_score", "float1"),
        ]),
    "skillsbridge": ReportSpec(
        label="SkillsBridge", table="skills_indicators", date_col="observed_at",
        columns=["observed_at", "lga", "school_count", "school_density_per_10k",
                 "internet_coverage_pct", "mobile_coverage_pct", "learning_gap_index", "source"],
        metrics=[
            Metric("LGA observations", "rows"),
            Metric("Schools mapped", "sum", "school_count"),
            Metric("Avg internet coverage", "avg", "internet_coverage_pct", "pct"),
            Metric("Avg learning-gap index", "avg", "learning_gap_index", "float1"),
        ]),
}


def _spec(module: str) -> ReportSpec:
    spec = REPORT_SPECS.get(module)
    if spec is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "UNKNOWN_MODULE",
                                    "message": f"No report for module {module!r}."})
    return spec


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "TENANT_REQUIRED",
                                    "message": "An X-Tenant-Id header is required for reports."})
    return tenant_id


def _window(from_: str | None, to: str | None) -> tuple[datetime, datetime]:
    try:
        end = datetime.fromisoformat(to) if to else datetime.now(timezone.utc)
        start = datetime.fromisoformat(from_) if from_ else end - timedelta(days=365)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "BAD_DATE",
                                    "message": "from/to must be ISO dates (YYYY-MM-DD)."}) from exc
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if to and len(to) <= 10:
        end = end + timedelta(days=1) - timedelta(seconds=1)
    return start, end


async def _fetch(session: AsyncSession, spec: ReportSpec, cols: list[str],
                 start: datetime, end: datetime) -> list[dict]:
    select = ", ".join(dict.fromkeys(cols))  # de-dupe, preserve order
    rows = await session.execute(
        text(
            f"SELECT {select} FROM {spec.table} "  # noqa: S608 — table+cols from fixed specs
            f"WHERE {spec.date_col} BETWEEN :start AND :end "
            f"ORDER BY {spec.date_col} DESC"
        ),
        {"start": start, "end": end},
    )
    return [dict(r) for r in rows.mappings().all()]


def _fmt(value: float, fmt: str) -> str:
    if fmt == "ngn":
        return f"₦{value:,.0f}"
    if fmt == "frac_pct":          # 0–1 fraction → percentage
        return f"{value * 100:.0f}%"
    if fmt == "pct":               # already a 0–100 percentage
        return f"{value:.1f}%"
    if fmt == "float1":
        return f"{value:,.1f}"
    return f"{int(round(value)):,}"


def _compute_metric(rows: list[dict], m: Metric) -> str:
    if m.agg == "rows":
        return f"{len(rows):,}"
    if m.column is None:
        return "—"
    vals = [r[m.column] for r in rows if r.get(m.column) is not None]
    if m.agg == "distinct":
        return f"{len({r[m.column] for r in rows if r.get(m.column) is not None}):,}"
    nums = [float(v) for v in vals if isinstance(v, (int, float))]
    if not nums:
        return "—"
    if m.agg == "sum":
        return _fmt(sum(nums), m.fmt)
    if m.agg == "avg":
        return _fmt(sum(nums) / len(nums), m.fmt)
    return "—"


def _summary(module: str, spec: ReportSpec, rows: list[dict],
             start: datetime, end: datetime) -> ReportSummary:
    # `rows` already holds the metric + breakdown columns (fetched in the handler).
    metrics = [ReportMetric(label=m.label, display=_compute_metric(rows, m))
               for m in spec.metrics]
    breakdown = None
    if spec.breakdown_col:
        counts: dict[str, int] = {}
        for r in rows:
            k = r.get(spec.breakdown_col)
            if k is not None:
                counts[str(k)] = counts.get(str(k), 0) + 1
        breakdown = ReportBreakdown(
            title=spec.breakdown_title or spec.breakdown_col,
            rows=[ReportBreakdownRow(key=k, count=v)
                  for k, v in sorted(counts.items(), key=lambda x: -x[1])],
        )
    return ReportSummary(
        module=module, label=spec.label,
        date_from=start.date().isoformat(), date_to=end.date().isoformat(),
        total_rows=len(rows), metrics=metrics, breakdown=breakdown,
    )


@router.get("/modules", response_model=SuccessResponse[list[ReportModuleInfo]])
async def report_modules() -> SuccessResponse[list[ReportModuleInfo]]:
    return SuccessResponse(
        data=[ReportModuleInfo(key=k, label=s.label) for k, s in REPORT_SPECS.items()],
        meta=build_meta(),
    )


# ─── Scheduled report subscriptions (super-admin) ─────────────────────────

async def _list_subs(session: AsyncSession) -> list[ReportSubscription]:
    rows = (await session.execute(text(
        "SELECT id, tenant_id, module, frequency, recipient_email, enabled, "
        "last_sent_at, created_at FROM public.report_subscriptions "
        "ORDER BY tenant_id, module"
    ))).mappings().all()
    return [ReportSubscription(**r) for r in rows]


@router.get("/subscriptions", response_model=SuccessResponse[list[ReportSubscription]])
async def list_subscriptions(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[list[ReportSubscription]]:
    return SuccessResponse(data=await _list_subs(session), meta=build_meta())


@router.post("/subscriptions", response_model=SuccessResponse[ReportSubscription],
             status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: ReportSubscriptionCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> SuccessResponse[ReportSubscription]:
    if body.module not in REPORT_SPECS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "UNKNOWN_MODULE",
                                    "message": f"No report for module {body.module!r}."})
    row = (await session.execute(
        text(
            """
            INSERT INTO public.report_subscriptions
                (tenant_id, module, frequency, recipient_email)
            VALUES (:t, :m, :f, :e)
            ON CONFLICT (tenant_id, module, recipient_email, frequency)
              DO UPDATE SET enabled = TRUE
            RETURNING id, tenant_id, module, frequency, recipient_email, enabled,
                      last_sent_at, created_at
            """
        ),
        {"t": body.tenant_id, "m": body.module, "f": body.frequency,
         "e": str(body.recipient_email).strip().lower()},
    )).mappings().first()
    await session.commit()
    return SuccessResponse(data=ReportSubscription(**row), meta=build_meta())


@router.delete("/subscriptions/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    sub_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[CurrentUser, Depends(require_super_admin)],
) -> None:
    await session.execute(
        text("DELETE FROM public.report_subscriptions WHERE id = CAST(:id AS uuid)"),
        {"id": sub_id},
    )
    await session.commit()


@router.get("/summary", response_model=SuccessResponse[ReportSummary])
async def report_summary(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    module: Annotated[str, Query()] = "farmland",
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
) -> SuccessResponse[ReportSummary]:
    _require_tenant(request)
    spec = _spec(module)
    start, end = _window(from_, to)
    cols = [m.column for m in spec.metrics if m.column]
    if spec.breakdown_col:
        cols.append(spec.breakdown_col)
    rows = await _fetch(session, spec, cols or [spec.date_col], start, end)
    return SuccessResponse(data=_summary(module, spec, rows, start, end), meta=build_meta())


@router.get("/export.csv")
async def report_export_csv(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    module: Annotated[str, Query()] = "farmland",
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    tenant_id = _require_tenant(request)
    spec = _spec(module)
    start, end = _window(from_, to)
    rows = await _fetch(session, spec, spec.columns, start, end)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(spec.columns)
    for r in rows:
        writer.writerow([r.get(c) for c in spec.columns])
    buf.seek(0)
    fname = f"{tenant_id}_{module}_{start.date().isoformat()}_{end.date().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/export.pdf")
async def report_export_pdf(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    module: Annotated[str, Query()] = "farmland",
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    tenant_id = _require_tenant(request)
    _spec(module)  # validate
    start, end = _window(from_, to)
    _, pdf = await render_report(session, tenant_id, module, start, end)
    fname = f"{tenant_id}_{module}_{start.date().isoformat()}_{end.date().isoformat()}.pdf"
    return StreamingResponse(
        iter([pdf]), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


async def render_report(
    session: AsyncSession, tenant_id: str, module: str,
    start: datetime, end: datetime,
) -> tuple[ReportSummary, bytes]:
    """Build (summary, pdf_bytes) for a tenant+module over a window. Shared by the
    HTTP export endpoint and the scheduled-report job. The caller is responsible
    for the session's search_path being pinned to the tenant."""
    spec = REPORT_SPECS[module]
    cols = [m.column for m in spec.metrics if m.column]
    if spec.breakdown_col:
        cols.append(spec.breakdown_col)
    cols.append(spec.date_col)
    rows = await _fetch(session, spec, cols, start, end)
    summary = _summary(module, spec, rows, start, end)
    monthly = _monthly(rows, spec.date_col)
    return summary, _build_pdf(tenant_id, summary, monthly)


def _monthly(rows: list[dict], date_col: str) -> list[tuple[str, int]]:
    """Records per calendar month (YYYY-MM) over the window, sorted ascending."""
    counts: dict[str, int] = {}
    for r in rows:
        d = r.get(date_col)
        if d is None:
            continue
        key = f"{d.year}-{d.month:02d}"
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items())


_CHART_PALETTE = ["#2d6a4f", "#c1440e", "#c97d00", "#1d3557", "#6b2d5e",
                  "#52b788", "#74a7d5", "#f4a832"]


def _bar_drawing(data: list[tuple[str, int]]):
    """Vertical bar chart of (label, value) — used for the monthly trend."""
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.colors import HexColor

    d = Drawing(440, 170)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 35, 30, 390, 120
    bc.data = [[v for _, v in data]]
    bc.categoryAxis.categoryNames = [k for k, _ in data]
    bc.categoryAxis.labels.angle = 30
    bc.categoryAxis.labels.dy = -8
    bc.categoryAxis.labels.fontSize = 7
    bc.valueAxis.valueMin = 0
    bc.bars[0].fillColor = HexColor("#2d6a4f")
    d.add(bc)
    return d


def _pie_drawing(data: list[tuple[str, int]]):
    """Pie chart of (label, value) — used for the categorical breakdown."""
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.colors import HexColor

    d = Drawing(440, 170)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 20, 20, 130, 130
    pie.data = [v for _, v in data]
    pie.slices.strokeWidth = 0.5
    colors_ = [HexColor(_CHART_PALETTE[i % len(_CHART_PALETTE)]) for i in range(len(data))]
    for i in range(len(data)):
        pie.slices[i].fillColor = colors_[i]
    d.add(pie)
    legend = Legend()
    legend.x, legend.y = 180, 140
    legend.fontSize = 8
    legend.dxTextSpace = 5
    legend.deltay = 12
    legend.colorNamePairs = [(colors_[i], f"{k} ({v})") for i, (k, v) in enumerate(data)]
    d.add(legend)
    return d


def _build_pdf(tenant_id: str, s: ReportSummary, monthly: list[tuple[str, int]]) -> bytes:
    # Imported lazily so the rest of the service doesn't pay for reportlab.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"{tenant_id} {s.label} report",
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=20 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    flow = [
        Paragraph(f"EconomicBridge — {s.label} Report", styles["Title"]),
        Paragraph(f"Tenant: <b>{tenant_id}</b> &nbsp;·&nbsp; Period: "
                  f"{s.date_from} to {s.date_to} &nbsp;·&nbsp; {s.total_rows:,} records",
                  styles["Normal"]),
        Spacer(1, 8 * mm),
    ]

    metric_data = [["Metric", "Value"]] + [[m.label, m.display] for m in s.metrics]
    t = Table(metric_data, colWidths=[90 * mm, 70 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d6a4f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f1eb")]),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(t)

    # Monthly trend chart — the historical shape over the window.
    if len(monthly) >= 2:
        flow.append(Spacer(1, 8 * mm))
        flow.append(Paragraph("<b>Records per month</b>", styles["Normal"]))
        flow.append(Spacer(1, 2 * mm))
        flow.append(_bar_drawing(monthly))

    if s.breakdown and s.breakdown.rows:
        flow.append(Spacer(1, 8 * mm))
        flow.append(Paragraph(f"<b>{s.breakdown.title}</b>", styles["Normal"]))
        flow.append(Spacer(1, 2 * mm))
        # Pie for ≤8 categories; the table below always lists exact counts.
        if 2 <= len(s.breakdown.rows) <= 8:
            flow.append(_pie_drawing([(r.key, r.count) for r in s.breakdown.rows]))
            flow.append(Spacer(1, 2 * mm))
        bd = [["Category", "Count"]] + [[r.key, str(r.count)] for r in s.breakdown.rows]
        bt = Table(bd, colWidths=[90 * mm, 70 * mm])
        bt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d3557")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        flow.append(bt)

    flow.append(Spacer(1, 12 * mm))
    flow.append(Paragraph(
        "Generated by EconomicBridge · operated by Bizra Farms Integrated Nigeria Ltd. "
        "Figures are scoped to the tenant and period above.",
        styles["Italic"]))
    doc.build(flow)
    return buf.getvalue()
