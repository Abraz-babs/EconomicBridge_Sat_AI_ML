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
        "act_rainfall": "Check low-lying fields and drainage.",
        "act_default": "Avoid affected area.",
        "optout": "Reply STOP to opt out.",
        "sev": {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"},
        "types": {"conflict": "Conflict", "flood": "Flood", "drought": "Drought", "fire": "Fire",
                  "rainfall": "Heavy rainfall"},
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
        "types": {"conflict": "conflit", "flood": "inondation", "drought": "secheresse", "fire": "incendie",
                  "rainfall": "Fortes pluies"},
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
        "types": {"conflict": "conflito", "flood": "inundacao", "drought": "seca", "fire": "incendio",
                  "rainfall": "Chuva forte"},
    },
    # ── DRAFT — pending native-speaker review (do not treat as final) ──
    "ha": {
        "brand": "EconomicBridge",
        "alert": "Fadakarwar {type} a {where}, {state}.",
        "eta": "Cikin awa {h}.",
        "area": "Hekta {ha} cikin hadari.",
        "act_conflict": "Ku kawar da dabbobi daga iyaka.",
        "act_rainfall": "Ku duba gonaki masu kasa da magudanar ruwa.",
        "act_default": "Ku guji wurin da abin ya shafa.",
        "optout": "Aika STOP don dainawa.",
        "sev": {"critical": "MAI TSANANI", "high": "BABBA", "medium": "MATSAKAICI", "low": "KARAMI"},
        "types": {"conflict": "rikici", "flood": "ambaliya", "drought": "fari", "fire": "gobara",
                  "rainfall": "ruwan sama mai yawa"},
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
    # Rainfall gets its own advice. "Avoid affected area" is wrong for a
    # rainfall reading — nothing has happened to avoid; the useful action is
    # to go and look at the fields most likely to be affected.
    if ctx.alert_type == "conflict":
        action = p["act_conflict"]
    elif ctx.alert_type == "rainfall":
        action = p.get("act_rainfall", p["act_default"])
    else:
        action = p["act_default"]

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


# ─── Farmer advisories ────────────────────────────────────────────────────
#
# Separate from _PHRASES above, on purpose. That pack assembles a fragment
# format built for an agency desk — "[CRITICAL] EconomicBridge — Flood alert in
# X. ETA 48h. 120 ha at risk." A farmer holding a feature phone needs the
# opposite: no severity shouting, no hectares, no ETA, one observation and one
# thing to do.
#
# Every template states what was OBSERVED and never what is expected. We have no
# forecasting capability, and a farmer who reads "rain is expected" may delay
# moving stored grain on a prediction that does not exist behind the message.
#
# Hausa reviewed by the operator (native speaker, Kebbi) 2026-08-10, with two
# phrases adjusted afterwards — see FARMER_HA_PENDING_CONFIRMATION.
FARMER_ADVISORIES: dict[str, dict[str, str]] = {
    "en": {
        "enrolment":
            "EconomicBridge: you now get free satellite farm advisories for "
            "{lga}, {state}, from Bizra Farms. About 2-4 msgs a month. "
            "Reply STOP to opt out.",
        "rainfall":
            "EconomicBridge advisory: heavy rain recorded in {lga}, {state}. "
            "Check low-lying fields and clear drainage channels. "
            "Reply STOP to opt out.",
        "fire":
            "EconomicBridge advisory: fire activity seen near {lga}, {state}. "
            "Check firebreaks and stored harvest. Reply STOP to opt out.",
        "crop_stress":
            "EconomicBridge advisory: crop vigour in {lga}, {state} is below "
            "normal now. Check fields for pests, disease or dry soil. "
            "Reply STOP to opt out.",
        "land_change":
            "EconomicBridge advisory: unusual land change seen near {lga}, "
            "{state}. Please inspect your farm boundary when you can. "
            "Reply STOP to opt out.",
    },
    "ha": {
        "enrolment":
            "EconomicBridge: yanzu kuna samun shawarwarin noma na tauraron dan "
            "adam kyauta a {lga}, {state}, daga Bizra Farms. Sako 2-4 a wata. "
            "Aika STOP don dainawa.",
        # "an yi" (rain FELL), not "ana tsammanin" (rain is EXPECTED). The
        # advisory fires on rainfall already measured; we cannot forecast.
        "rainfall":
            "Shawarar EconomicBridge: an yi ruwan sama mai yawa a {lga}, "
            "{state}. Ku duba gonakin kwarai, ku share magudanan ruwa. "
            "Aika STOP don dainawa.",
        "fire":
            "Shawarar EconomicBridge: an hango alamar wutar daji kusa da "
            "{lga}, {state}. Ku duba shingen wuta da amfanin gonar da kuka "
            "ajiye. Aika STOP don dainawa.",
        "crop_stress":
            "Shawarar EconomicBridge: lafiyar amfanin gona a {lga}, {state} ya "
            "ragu a yanzu. Ku duba gonaki don kwari, cuta ko kasa mai bushewa. "
            "Aika STOP don dainawa.",
        # Shortened: the original ran to 172 characters at the longest LGA
        # name, which splits into two segments and doubles the cost.
        "land_change":
            "Shawarar EconomicBridge: an hango canjin kasa wanda ba a saba samu "
            "ba kusa da {lga}, {state}. Ku duba iyakar gonarku. "
            "Aika STOP don dainawa.",
    },
}

# The two Hausa phrases changed after the operator's review. Neither is a
# translation of new content — one fixes tense, one shortens for cost — but a
# native speaker should confirm both before these reach a real recipient.
FARMER_HA_PENDING_CONFIRMATION: tuple[str, ...] = ("rainfall", "land_change")

# Alert types that are NOT offered here, and must not be added without evidence:
#   drought  — the detector has no seasonal awareness; when the rains end,
#              NDVI falls naturally and it fires on nearly every LGA.
#   flood    — tested against the documented Sept 2024 Kebbi flooding and
#              identified none of the eleven affected LGAs.
#   conflict — the 24-72h prediction has never been validated against recorded
#              incidents, and a message that moves someone toward or away from
#              a boundary on an unvalidated signal could get a person hurt.
FARMER_WITHHELD: tuple[str, ...] = ("drought", "flood", "conflict")

SMS_SINGLE_SEGMENT_CHARS = 160


def render_farmer_sms(
    advisory: str, *, lga: str, state: str, lang: str = "en"
) -> str:
    """One farmer-facing SMS. Falls back to English for an unknown language.

    Raises for a withheld advisory type rather than rendering it — the reason
    each is withheld is in FARMER_WITHHELD, and none should reach a farmer on
    the strength of a caller passing the wrong string.
    """
    if advisory in FARMER_WITHHELD:
        raise ValueError(
            f"'{advisory}' is withheld from farmer SMS: see FARMER_WITHHELD "
            f"in services/messages.py for why"
        )
    pack = FARMER_ADVISORIES.get(lang, FARMER_ADVISORIES["en"])
    template = pack.get(advisory) or FARMER_ADVISORIES["en"].get(advisory)
    if template is None:
        raise ValueError(f"unknown farmer advisory type: {advisory!r}")
    return template.format(lga=lga, state=state)
