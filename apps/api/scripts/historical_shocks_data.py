"""Documented historical flood/drought events for the pilot tenants.

EVERY row here is a REAL, recorded event with a citable source. This file
replaces the invented "plausible" fixtures that scripts/seed_shockguard_events.py
used to write (those were labelled HISTORICAL in the UI, which implied they had
actually happened — they had not).

Rules for adding an entry — do not relax them:
  * The event must have OCCURRED and be documented by a named source with a URL
    (IOM DTM / OCHA / ReliefWeb situation reports, NEMA, or major wire coverage).
  * `lgas` lists only LGAs the source ACTUALLY names as affected. When a source
    reports at state level without an LGA breakdown, leave `lgas` empty and set
    `lga_breakdown_published=False` — the loader then writes one statewide row.
    Never guess an LGA to make a map look fuller.
  * Casualty/impact figures are copied from the source, not estimated. Where
    sources disagree (common as a disaster is still being assessed), take the
    figure from the most authoritative post-event assessment and say so in
    `note`.
  * A government FORECAST ("31 states at high risk") is NOT an event. Only
    recorded impact counts.
  * Record EVERY documented rainy-season disaster, not just floods — the point
    is to show what we capture across the season. Differentiate by
    `event_type` (flood / drought / rainstorm / windstorm / landslide /
    erosion); never force one hazard into another's label to fit a schema.
    Migration 0036 widened the DB CHECK for exactly this.

Tenants with no verified entry are deliberately left absent rather than filled
with plausible-looking rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HistoricalShock:
    """One documented disaster, as reported by `source_name`."""

    event_date: date
    event_type: str                  # 'flood' | 'drought'
    title: str
    severity: str                    # low | medium | high | critical
    source_name: str
    source_url: str
    lgas: tuple[str, ...] = ()
    deaths: int | None = None
    people_affected: int | None = None
    households_affected: int | None = None
    houses_destroyed: int | None = None
    farmland_hectares: int | None = None
    note: str = ""
    lga_breakdown_published: bool = True

    def as_metrics(self) -> dict[str, object]:
        """JSONB payload — carries the provenance the UI cites."""
        m: dict[str, object] = {
            "record_type": "documented_historical_event",
            "event_date": self.event_date.isoformat(),
            "title": self.title,
            "source": self.source_name,
            "source_url": self.source_url,
            "lga_breakdown_published": self.lga_breakdown_published,
        }
        for key, val in (
            ("deaths", self.deaths),
            ("people_affected", self.people_affected),
            ("households_affected", self.households_affected),
            ("houses_destroyed", self.houses_destroyed),
            ("farmland_hectares", self.farmland_hectares),
        ):
            if val is not None:
                m[key] = val
        if self.note:
            m["note"] = self.note
        return m


# ─── Nigeria ──────────────────────────────────────────────────────────────

_KEBBI_2024 = HistoricalShock(
    event_date=date(2024, 9, 1),
    event_type="flood",
    title="2024 rainy-season floods — 16 of 21 LGAs affected",
    severity="critical",
    deaths=32,
    people_affected=280230,
    households_affected=54617,
    # The 16 LGAs the joint assessment names as affected.
    lgas=(
        "Bagudu", "Augie", "Argungu", "Gwandu", "Birnin Kebbi", "Maiyama",
        "Jega", "Koko-Besse", "Yauri", "Ngaski", "Shanga", "Kalgo",
        "Bunza", "Suru", "Arewa Dandi", "Aleiro",
    ),
    note=(
        "Rice and millet farmland, roads, bridges, schools and health "
        "facilities damaged across the Rima/Niger floodplain."
    ),
    source_name="IOM DTM / NEMA — Joint Post-Flood Situation Report, Kebbi State (30 Sep 2024)",
    source_url=(
        "https://reliefweb.int/report/nigeria/"
        "nigeria-joint-post-flood-situation-report-kebbi-state-30-september-2024"
    ),
)

_KEBBI_ARGUNGU_2024 = HistoricalShock(
    event_date=date(2024, 8, 4),
    event_type="flood",
    title="Argungu flash flood — Bayawa, Tiggi and Fakon Sarki villages",
    severity="high",
    houses_destroyed=200,
    people_affected=300,
    lgas=("Argungu",),
    note="Early-season flood that preceded the wider September peak.",
    source_name="Channels Television (4 Aug 2024)",
    source_url=(
        "https://www.channelstv.com/2024/08/04/"
        "over-200-houses-destroyed-as-flooding-devastates-villages-in-argungu-kebbi/"
    ),
)

_NIGER_MOKWA_2025 = HistoricalShock(
    event_date=date(2025, 5, 29),
    event_type="flood",
    title="Mokwa flood disaster — Tiffin Maza and Anguwan Hausawa",
    severity="critical",
    deaths=151,
    houses_destroyed=4000,
    lgas=("Mokwa",),
    note=(
        "Torrential rain plus failure of an old railway embankment. 151 deaths "
        "confirmed in the days after; later official counts ran higher while "
        "search continued. Two bridges collapsed."
    ),
    source_name="UN News (Jun 2025)",
    source_url="https://news.un.org/en/story/2025/06/1163951",
)

_NIGER_2024 = HistoricalShock(
    event_date=date(2024, 9, 12),
    event_type="flood",
    title="2024 rainy-season floods — Niger State assessment",
    severity="high",
    lga_breakdown_published=False,
    note="Assessed by the IOM Displacement Tracking Matrix flood assessment team.",
    source_name="IOM DTM — Nigeria Flood Situation Report, Niger State (12 Sep 2024)",
    source_url=(
        "https://dtm.iom.int/sites/g/files/tmzbdl1461/files/reports/"
        "Nigeria%20-%20Flood%20Assessment%20Report%20Niger%20State%20"
        "13%20September%202024_final_0.pdf"
    ),
)

_BENUE_2022 = HistoricalShock(
    event_date=date(2022, 9, 26),
    event_type="flood",
    title="River Benue flooding after the Lagdo Dam release",
    severity="critical",
    lgas=("Makurdi", "Agatu", "Gwer West"),
    note=(
        "Cameroon's Lagdo Dam began releasing excess water on 13 Sep 2022; the "
        "Benue channel overtopped through late September into October. "
        "Displaced households from Ankpa/Wadata ward sheltered at Ichwa Camp."
    ),
    source_name="Copernicus EMS / ReliefWeb — flood extent along the River Benue channel (26 Sep 2022)",
    source_url=(
        "https://reliefweb.int/map/nigeria/"
        "nigeria-flood-extent-along-river-benue-channel-agatu-doma-gwer-west-and-"
        "makurdi-lgas-upstream-loko-26-sep-2022"
    ),
)

_NASARAWA_2022 = HistoricalShock(
    event_date=date(2022, 9, 26),
    event_type="flood",
    title="River Benue flooding — Doma LGA (Lagdo Dam release)",
    severity="high",
    lgas=("Doma",),
    note=(
        "Same Benue-channel event as Benue State; Doma sits on the mapped flood "
        "extent upstream of Loko. Farmland along the river was inundated."
    ),
    source_name="Copernicus EMS / ReliefWeb — flood extent along the River Benue channel (26 Sep 2022)",
    source_url=(
        "https://reliefweb.int/map/nigeria/"
        "nigeria-flood-extent-along-river-benue-channel-agatu-doma-gwer-west-and-"
        "makurdi-lgas-upstream-loko-26-sep-2022"
    ),
)

_KADUNA_2024 = HistoricalShock(
    event_date=date(2024, 9, 1),
    event_type="flood",
    title="2024 rainy-season floods — 7 LGAs assessed",
    severity="medium",
    people_affected=9616,
    households_affected=1668,
    lga_breakdown_published=False,
    note=(
        "The joint assessment covered 7 LGAs but the published summary does not "
        "name them, so this is recorded statewide rather than guessed per-LGA."
    ),
    source_name="IOM DTM / NEMA — Joint Post-Flood Situation Report, Kaduna State (31 Dec 2024)",
    source_url=(
        "https://reliefweb.int/report/nigeria/"
        "nigeria-joint-post-flood-situation-report-kaduna-state-31-december-2024"
    ),
)

_FCT_2024 = HistoricalShock(
    event_date=date(2024, 6, 24),
    event_type="flood",
    title="Trademore Estate flash flood, Lugbe",
    severity="high",
    deaths=2,
    lgas=("Municipal Area Council",),
    note=(
        "Pre-dawn torrential downpour submerged houses in Trademore Estate, "
        "Lugbe — a recurrent flashpoint on a built-over floodplain."
    ),
    source_name="IOM DTM / NEMA — Joint Post-Flood Situation Report, FCT (30 Dec 2024)",
    source_url=(
        "https://reliefweb.int/report/nigeria/"
        "nigeria-joint-post-flood-situation-report-fct-30-december-2024"
    ),
)

_ZAMFARA_2024 = HistoricalShock(
    event_date=date(2024, 9, 17),
    event_type="flood",
    title="2024 rainy-season floods — among the hardest-hit states",
    severity="high",
    lga_breakdown_published=False,
    note=(
        "OCHA's national flood overview groups Zamfara with the hardest-hit "
        "states; the overview reports nationally (5.26m affected, 1,237 deaths, "
        "321 LGAs) without a Zamfara LGA breakdown."
    ),
    source_name="OCHA — Nigeria Flood Overview (17 Sep 2024)",
    source_url=(
        "https://reliefweb.int/report/nigeria/nigeria-flood-overview-17-september-2024"
    ),
)

# ─── ECOWAS pilots ────────────────────────────────────────────────────────

_GHANA_AKOSOMBO_2023 = HistoricalShock(
    event_date=date(2023, 10, 15),
    event_type="flood",
    title="Akosombo and Kpong dam controlled spillage — Lower Volta",
    severity="critical",
    people_affected=35857,
    lgas=("North Tongu", "Central Tongu"),
    note=(
        "The Volta River Authority began controlled spillage on 15 Sep 2023 "
        "after heavy rain filled the reservoirs; spillage ran to end-October. "
        "Mepe, Battor, Sogakope, Mafi, Adidome and Ada were worst hit; 35,857 "
        "people affected as of 17 Nov 2023."
    ),
    source_name="ReliefWeb — Ghana: Floods (Oct 2023) disaster page",
    source_url="https://reliefweb.int/disaster/fl-2023-000215-gha",
)

_PLATEAU_2025 = HistoricalShock(
    event_date=date(2025, 8, 17),
    event_type="flood",
    title="Shendam floods — Shimankar district communities",
    severity="high",
    houses_destroyed=50,
    lgas=("Shendam",),
    note=(
        "NEMA's Jos Operations Office ran an on-the-spot assessment of the "
        "flood-ravaged communities: Shimankar, Kalong, Anguwan Dadi, Unguwan "
        "Yargam, Wali, Gisa and Unguwan Zam. Over 50 houses plus schools and a "
        "worship centre destroyed in Menkaat, Shimankar district."
    ),
    source_name="Daily Post — NEMA on-the-spot assessment, Plateau (17 Aug 2025)",
    source_url=(
        "https://dailypost.ng/2025/08/17/"
        "plateau-nema-conducts-on-the-spot-assessment-in-flood-ravaged-communities/"
    ),
)

_PLATEAU_RIYOM_2026 = HistoricalShock(
    event_date=date(2026, 6, 2),
    event_type="rainstorm",
    title="Riyom rainstorm — Tom Gangare, Sopp Ward",
    severity="high",
    houses_destroyed=100,
    lgas=("Riyom",),
    note=(
        "Violent rainstorm levelled over 100 houses and displaced families; "
        "health facilities, places of worship and other infrastructure "
        "destroyed. Recorded as a rainstorm, not a flood — the damage was "
        "wind and rain impact, with no reported inundation."
    ),
    source_name="Daily Post (2 Jun 2026)",
    source_url=(
        "https://dailypost.ng/2026/06/02/"
        "rainstorm-destroys-100-houses-displaces-families-in-plateau-community/"
    ),
)

_PLATEAU_BASSA_2026 = HistoricalShock(
    event_date=date(2026, 7, 20),
    event_type="rainstorm",
    title="Bassa rainstorm — Zogot community",
    severity="medium",
    houses_destroyed=20,
    lgas=("Bassa",),
    note=(
        "Heavy downpour destroyed more than 20 houses and displaced several "
        "families; farmland and household property damaged."
    ),
    source_name="allAfrica / Vanguard (20 Jul 2026)",
    source_url="https://allafrica.com/stories/202607200089.html",
)

# ─── Rainstorms / windstorms ──────────────────────────────────────────────
# Recorded as their own type, not folded into 'flood'. These are wind-and-rain
# damage events: roofs off, mud walls down, no inundation. Our satellites
# cannot see them (validated 2026-07-26 — daily rainfall totals on these days
# are ordinary), so the register grows here only from documented reports.

_NIGER_WINDSTORM_2026 = HistoricalShock(
    event_date=date(2026, 5, 8),
    event_type="rainstorm",
    title="Windstorm across six LGAs — 1,000+ houses destroyed",
    severity="critical",
    houses_destroyed=1000,
    lgas=("Mokwa", "Bida", "Lavun", "Katcha", "Gbako", "Mariga"),
    note=(
        "Communities named include Sawmill, Kpege and Tifin Madza (Mokwa), "
        "Cheniyan and Masaga (Bida) and Durgu (Mariga). NSEMA began rapid "
        "assessment. No deaths reported. Struck the same Mokwa LGA that the "
        "2025 flood devastated — a different hazard, a year apart."
    ),
    source_name="Punch (8 May 2026)",
    source_url=(
        "https://punchng.com/"
        "windstorm-destroys-over-1000-houses-displaces-residents-in-niger-communities/"
    ),
)

_KEBBI_WINDSTORM_2026 = HistoricalShock(
    event_date=date(2026, 5, 6),
    event_type="rainstorm",
    title="Suru windstorm — houses and food stores destroyed",
    severity="high",
    lgas=("Suru",),
    note=(
        "Sambera, Jeroki, Becinga, Nassarawa, Tunga Soja, Tauken Mage, Tunga "
        "Muminu Oro and Ciwan Wanzam hit on the Wednesday night. Houses, food "
        "storage and property destroyed; residents reported no lives lost. "
        "House count not published, so none is recorded here."
    ),
    source_name="Punch (8 May 2026)",
    source_url="https://punchng.com/windstorm-ravages-kebbi-communities-destroys-houses/",
)

_KADUNA_RAINSTORM_2026 = HistoricalShock(
    event_date=date(2026, 5, 4),
    event_type="rainstorm",
    title="Chikun rainstorm — Dokan Mai-Jama'a and Sabon Gyero",
    severity="high",
    deaths=2,
    houses_destroyed=50,
    lgas=("Chikun",),
    note=(
        "Monday-evening storm lasting over 40 minutes; the village head "
        "reported 50+ houses severely affected, many flattened. Families left "
        "homeless."
    ),
    source_name="Punch (6 May 2026)",
    source_url="https://punchng.com/rainstorm-kills-two-ravages-50-kaduna-homes/",
)

_ZAMFARA_WINDSTORM_2026 = HistoricalShock(
    event_date=date(2026, 5, 10),
    event_type="rainstorm",
    title="Bungudu windstorm — Bela village",
    severity="high",
    deaths=1,
    houses_destroyed=200,
    lgas=("Bungudu",),
    note=(
        "Storm began late Sunday evening and lasted over an hour; 200+ houses "
        "destroyed in Bela village, hundreds displaced. Date is the report "
        "date — the storm struck the preceding Sunday night."
    ),
    source_name="Daily Trust (May 2026)",
    source_url="https://dailytrust.com/windstorm-kills-1-destroys-over-200-houses-in-zamfara/",
)

_SENEGAL_2022 = HistoricalShock(
    event_date=date(2022, 8, 6),
    event_type="flood",
    title="August 2022 floods — Dakar, Thiès and Matam",
    severity="high",
    houses_destroyed=170,
    households_affected=1396,
    lgas=("Dakar", "Thies", "Matam"),
    note=(
        "Dakar, Thiès and Matam recorded close to 500 mm between 5–7 Aug 2022. "
        "Worst damage at Yeumbeul Nord / Cambérène in Keur Massar department "
        "(carved out of Pikine in 2021, so it is recorded here against the three "
        "regions the source names); the Emergence and Keur Massar bridges collapsed."
    ),
    source_name="IFRC — Senegal Floods DREF Operation MDRSN019 (ReliefWeb)",
    source_url=(
        "https://reliefweb.int/report/senegal/"
        "senegal-floods-dakar-thies-and-matam-emergency-plan-action-epoa-dref-"
        "operation-ndeg-mdrsn019"
    ),
)


# Tenant → its documented events. A tenant with no verified event would be
# ABSENT on purpose (see module docstring) rather than filled with invented
# rows; all 10 pilots currently have at least one sourced event.
HISTORICAL_EVENTS: dict[str, tuple[HistoricalShock, ...]] = {
    "kebbi": (_KEBBI_2024, _KEBBI_ARGUNGU_2024, _KEBBI_WINDSTORM_2026),
    "niger": (_NIGER_MOKWA_2025, _NIGER_2024, _NIGER_WINDSTORM_2026),
    "benue": (_BENUE_2022,),
    "nasarawa": (_NASARAWA_2022,),
    "kaduna": (_KADUNA_2024, _KADUNA_RAINSTORM_2026),
    "fct": (_FCT_2024,),
    "zamfara": (_ZAMFARA_2024, _ZAMFARA_WINDSTORM_2026),
    "plateau": (_PLATEAU_2025, _PLATEAU_RIYOM_2026, _PLATEAU_BASSA_2026),
    "ghana": (_GHANA_AKOSOMBO_2023,),
    "senegal": (_SENEGAL_2022,),
}

# Tenants still needing a sourced event before they show any history.
# Empty: all 10 pilots now carry at least one documented event.
TENANTS_AWAITING_RESEARCH: tuple[str, ...] = ()

__all__ = [
    "HISTORICAL_EVENTS",
    "TENANTS_AWAITING_RESEARCH",
    "HistoricalShock",
]
