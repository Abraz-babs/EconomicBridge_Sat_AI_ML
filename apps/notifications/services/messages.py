"""SMS message templates per alert type + language.

Free-tier farmer alerts must be:
  - ≤ 160 chars where possible (one SMS segment = ~$0.005 vs ~$0.01 for two)
  - in the recipient's language
  - actionable (so the farmer knows what to do)

For Step 10 we ship English templates only; Hausa/Yoruba/Igbo/French/
Portuguese translations land in Step 10.1 with a real translator review (do
NOT auto-translate alerts).
"""
from __future__ import annotations

from dataclasses import dataclass


TEMPLATE_NAME = "conflict_v1_en"

STATE_NAMES: dict[str, str] = {
    "kebbi":   "Kebbi",
    "benue":   "Benue",
    "plateau": "Plateau",
    "kaduna":  "Kaduna",
    "niger":   "Niger",
    "zamfara": "Zamfara",
    "fct":     "FCT",
    "ghana":   "Ghana",
    "senegal": "Senegal",
}


@dataclass(frozen=True, slots=True)
class RenderContext:
    tenant_id: str
    severity: str
    alert_type: str
    lga: str | None
    zone_name: str | None
    affected_area_ha: float | None
    livelihoods_at_risk: int | None
    eta_hours: int | None


def render_conflict_sms(ctx: RenderContext) -> str:
    """Produce the SMS body for a conflict alert.

    Layout (~150 chars budget):
      [SEVERITY] EconomicBridge — <Type> alert in <LGA>, <State>.
      ETA <X>h. <Y> ha at risk. Move livestock from boundaries.
      Reply STOP to opt out.
    """
    state = STATE_NAMES.get(ctx.tenant_id, ctx.tenant_id.title())
    sev_label = ctx.severity.upper()
    where = ctx.lga or ctx.zone_name or state
    type_label = ctx.alert_type.replace("_", " ").title()
    eta = f"ETA {ctx.eta_hours}h." if ctx.eta_hours is not None else ""
    area = (
        f"{int(ctx.affected_area_ha)} ha at risk."
        if ctx.affected_area_ha is not None and ctx.affected_area_ha > 0
        else ""
    )
    action = (
        "Move livestock from boundaries."
        if ctx.alert_type == "conflict"
        else "Avoid affected area."
    )

    parts = [
        f"[{sev_label}] EconomicBridge",
        f"— {type_label} alert in {where}, {state}.",
        eta,
        area,
        action,
        "Reply STOP to opt out.",
    ]
    body = " ".join(p for p in parts if p)
    # Single-segment safety net — most carriers split at 160 chars for GSM-7
    # encoding. Anything longer just costs more, doesn't fail.
    return body[:480]


def should_dispatch(
    *, severity: str, threshold: str, alert_types: list[str] | None,
    incoming_alert_type: str,
) -> bool:
    """Match an incoming alert against a subscriber's preferences.

    `threshold` is one of 'critical' | 'high' | 'medium' | 'all'. We use a
    severity rank to compare (critical > high > medium > low). If
    `alert_types` is empty/None, the subscriber gets all types.
    """
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    threshold_rank = {"critical": 3, "high": 2, "medium": 1, "all": 0}
    if rank.get(severity, 0) < threshold_rank.get(threshold, 2):
        return False
    if alert_types and incoming_alert_type not in alert_types:
        return False
    return True
