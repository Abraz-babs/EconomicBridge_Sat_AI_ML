"""SMS message templates per alert type + language.

Free-tier farmer alerts must be:
  - short (GSM-7 single segment ≈ 160 chars; accented HA/YO/IG fall to UCS-2
    ≈ 70 chars/segment — correctness over cost, flagged below)
  - in the recipient's language
  - actionable (so the farmer knows what to do)

Languages: English, French, Portuguese are review-ready (VERIFIED_LANGUAGES).
Hausa, Yoruba and Igbo are DRAFT machine-assisted translations and MUST be
checked by a native speaker before production sends — do NOT treat them as
final. `is_verified(lang)` lets callers gate or warn. The renderer still
produces them so the capability can be demoed/piloted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Language = Literal["en", "fr", "pt", "ha", "yo", "ig"]

# Languages whose copy has been reviewed and is safe to send in production.
# HA/YO/IG are drafted but pending native-speaker sign-off.
VERIFIED_LANGUAGES: frozenset[str] = frozenset({"en", "fr", "pt"})

TEMPLATE_NAME = "conflict_v2_multilang"

STATE_NAMES: dict[str, str] = {
    "kebbi":   "Kebbi",
    "benue":   "Benue",
    "plateau": "Plateau",
    "kaduna":  "Kaduna",
    "niger":   "Niger",
    "zamfara": "Zamfara",
    "nasarawa": "Nasarawa",
    "fct":     "FCT",
    "ghana":   "Ghana",
    "senegal": "Senegal",
}


# Per-language phrase packs. `{type}/{where}/{state}/{h}/{ha}` are filled in.
# EN/FR/PT reviewed; HA/YO/IG are DRAFT (see module docstring).
_PHRASES: dict[str, dict] = {
    "en": {
        "brand": "EconomicBridge",
        "alert": "{type} alert in {where}, {state}.",
        "eta": "ETA {h}h.",
        "area": "{ha} ha at risk.",
        "act_conflict": "Move livestock from boundaries.",
        "act_default": "Avoid affected area.",
        "optout": "Reply STOP to opt out.",
        "sev": {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"},
        "types": {"conflict": "Conflict", "flood": "Flood", "drought": "Drought", "fire": "Fire"},
    },
    "fr": {
        "brand": "EconomicBridge",
        "alert": "Alerte {type} a {where}, {state}.",
        "eta": "Delai {h}h.",
        "area": "{ha} ha menaces.",
        "act_conflict": "Eloignez le betail des limites.",
        "act_default": "Evitez la zone touchee.",
        "optout": "Repondez STOP pour vous desabonner.",
        "sev": {"critical": "CRITIQUE", "high": "ELEVE", "medium": "MOYEN", "low": "FAIBLE"},
        "types": {"conflict": "conflit", "flood": "inondation", "drought": "secheresse", "fire": "incendie"},
    },
    "pt": {
        "brand": "EconomicBridge",
        "alert": "Alerta de {type} em {where}, {state}.",
        "eta": "Prazo {h}h.",
        "area": "{ha} ha em risco.",
        "act_conflict": "Afaste o gado dos limites.",
        "act_default": "Evite a area afetada.",
        "optout": "Responda STOP para cancelar.",
        "sev": {"critical": "CRITICO", "high": "ALTO", "medium": "MEDIO", "low": "BAIXO"},
        "types": {"conflict": "conflito", "flood": "inundacao", "drought": "seca", "fire": "incendio"},
    },
    # ── DRAFT — pending native-speaker review (do not treat as final) ──
    "ha": {
        "brand": "EconomicBridge",
        "alert": "Fadakarwar {type} a {where}, {state}.",
        "eta": "Cikin awa {h}.",
        "area": "Hekta {ha} cikin hadari.",
        "act_conflict": "Ku kawar da dabbobi daga iyaka.",
        "act_default": "Ku guji wurin da abin ya shafa.",
        "optout": "Aika STOP don dainawa.",
        "sev": {"critical": "MAI TSANANI", "high": "BABBA", "medium": "MATSAKAICI", "low": "KARAMI"},
        "types": {"conflict": "rikici", "flood": "ambaliya", "drought": "fari", "fire": "gobara"},
    },
    "yo": {
        "brand": "EconomicBridge",
        "alert": "Ikilo {type} ni {where}, {state}.",
        "eta": "Ninu wakati {h}.",
        "area": "Hekita {ha} wa ninu ewu.",
        "act_conflict": "Ko eran kuro ni agbegbe aala.",
        "act_default": "Yera fun agbegbe to kan.",
        "optout": "Fesi STOP lati yonda.",
        "sev": {"critical": "LEWU GAN", "high": "GIGA", "medium": "AARIN", "low": "KERE"},
        "types": {"conflict": "iforigbari", "flood": "ikun omi", "drought": "oda", "fire": "ina"},
    },
    "ig": {
        "brand": "EconomicBridge",
        "alert": "Okwa {type} na {where}, {state}.",
        "eta": "N'ime awa {h}.",
        "area": "Hekta {ha} no n'ihe egwu.",
        "act_conflict": "Wepu anu ulo site n'oke.",
        "act_default": "Zere ebe ahu emetutara.",
        "optout": "Zaa STOP ka i kwusi.",
        "sev": {"critical": "DI OKE NJO", "high": "ELU", "medium": "ETITI", "low": "ALA"},
        "types": {"conflict": "esemokwu", "flood": "idei mmiri", "drought": "uko mmiri", "fire": "oku"},
    },
}


def is_verified(lang: str) -> bool:
    """True if the language copy is reviewed and production-safe."""
    return lang in VERIFIED_LANGUAGES


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


def render_conflict_sms(ctx: RenderContext, lang: str = "en") -> str:
    """Produce the SMS body for a conflict/disaster alert in `lang`.

    Falls back to English for an unknown language code. HA/YO/IG render but
    are DRAFT (see module docstring) — callers can gate via is_verified().

    Layout (~150 char budget for GSM-7):
      [SEVERITY] EconomicBridge — <Type> alert in <LGA>, <State>.
      ETA <X>h. <Y> ha at risk. <action> Reply STOP to opt out.
    """
    p = _PHRASES.get(lang, _PHRASES["en"])
    state = STATE_NAMES.get(ctx.tenant_id, ctx.tenant_id.title())
    where = ctx.lga or ctx.zone_name or state
    sev = p["sev"].get(ctx.severity, ctx.severity.upper())
    type_label = p["types"].get(
        ctx.alert_type, ctx.alert_type.replace("_", " ").title()
    )

    alert_clause = p["alert"].format(type=type_label, where=where, state=state)
    eta = p["eta"].format(h=ctx.eta_hours) if ctx.eta_hours is not None else ""
    area = (
        p["area"].format(ha=int(ctx.affected_area_ha))
        if ctx.affected_area_ha is not None and ctx.affected_area_ha > 0
        else ""
    )
    action = p["act_conflict"] if ctx.alert_type == "conflict" else p["act_default"]

    parts = [
        f"[{sev}] {p['brand']}",
        f"— {alert_clause}",
        eta,
        area,
        action,
        p["optout"],
    ]
    body = " ".join(part for part in parts if part)
    # Length safety net — longer just costs more segments, never fails.
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
