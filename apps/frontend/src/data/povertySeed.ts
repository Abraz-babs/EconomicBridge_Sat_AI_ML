/**
 * Deterministic-per-tenant seed data for the Poverty Mapping module.
 *
 * Real ingestion (VIIRS nightlight, WorldPop, DHS, Landsat 9) lands in
 * a follow-up slice. For now the dashboard renders demo data hashed
 * from the tenant slug so it's stable across reloads + differs per
 * tenant for the visual story.
 */

const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};

const LGA_POOL: Record<string, string[]> = {
  kebbi:   ['Argungu', 'Birnin Kebbi', 'Dandi', 'Gwandu', 'Jega', 'Yauri', 'Zuru', 'Bunza'],
  benue:   ['Agatu', 'Logo', 'Tarka', 'Guma', 'Vandeikya', 'Otukpo', 'Apa', 'Buruku'],
  plateau: ['Bassa', 'Riyom', 'Bokkos', 'Jos North', 'Pankshin', 'Wase', 'Shendam', 'Mangu'],
  kaduna:  ['Birnin Gwari', 'Zangon Kataf', 'Kafanchan', 'Jaba', 'Kaura', 'Chikun', 'Igabi', 'Sabon Gari'],
  niger:   ['Shiroro', 'Kontagora', 'Mariga', 'Borgu', 'Lapai', 'Agaie', 'Suleja', 'Bida'],
  zamfara: ['Maru', 'Maradun', 'Anka', 'Bukkuyum', 'Gusau', 'Kaura Namoda', 'Tsafe', 'Talata Mafara'],
  nasarawa:['Akwanga', 'Wamba', 'Doma', 'Karu', 'Keffi', 'Lafia', 'Awe', 'Kokona'],
  fct:     ['Abaji', 'Bwari', 'Gwagwalada', 'Kuje', 'Kwali', 'AMAC'],
  ghana:   ['Pusiga', 'Garu-Tempane', 'Bawku', 'Tamale', 'Bolgatanga', 'Wa', 'Sunyani', 'Kumasi'],
  senegal: ['Sédhiou', 'Kolda', 'Tambacounda', 'Kédougou', 'Matam', 'Saint-Louis', 'Diourbel', 'Kaffrine'],
};


function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function rng(seed: number): () => number {
  let state = seed || 1;
  return () => {
    state = (state * 1664525 + 1013904223) | 0;
    return ((state >>> 0) % 100000) / 100000;
  };
}

function jitter(base: [number, number], lat: number, lon: number): [number, number] {
  return [base[0] + lon, base[1] + lat];
}


export interface PovertyVillage {
  id: string;
  name: string;
  lga: string;
  lon: number;
  lat: number;
  poverty_score: number;     // 0..1, higher = more vulnerable
  population: number;        // estimate
  hh_unreached: number;      // households not reached by aid
  nightlight_dimness: number;  // 0..1 — VIIRS-style metric
  has_dhs_data: boolean;
}

export interface PovertyStats {
  tenant_id: string;
  state_label: string;
  villages_identified: number;
  population_estimated: number;
  hh_unreached: number;
  coverage_pct: number;     // % of estimated pop reached by some aid
  verification_pct: number; // % of villages with DHS or ground-truth data
  villages: PovertyVillage[];
  hottest_village_id: string;
}


export function povertyStatsFor(
  tenantId: string,
  centroid: [number, number],
): PovertyStats {
  const lgas = LGA_POOL[tenantId] ?? [`${tenantId} Region 1`, `${tenantId} Region 2`];
  const r = rng(hashString(tenantId));
  const count = 8 + Math.floor(r() * 4);  // 8..11 villages
  const villages: PovertyVillage[] = [];

  for (let i = 0; i < count; i++) {
    const lga = lgas[i % lgas.length];
    const lonJitter = (r() - 0.5) * 1.6;
    const latJitter = (r() - 0.5) * 1.2;
    const [lon, lat] = jitter(centroid, latJitter, lonJitter);
    const poverty = 0.35 + r() * 0.6;
    const population = 800 + Math.floor(r() * 6_000);
    const unreached = Math.floor(population * (0.10 + r() * 0.35) / 4);
    villages.push({
      id: `${tenantId}-vil-${i}`,
      name: `${lga} settlement ${i + 1}`,
      lga,
      lon, lat,
      poverty_score: Math.min(0.99, poverty),
      population,
      hh_unreached: unreached,
      nightlight_dimness: 0.40 + r() * 0.55,
      has_dhs_data: r() > 0.35,
    });
  }

  const total_pop = villages.reduce((s, v) => s + v.population, 0);
  const total_unreached = villages.reduce((s, v) => s + v.hh_unreached, 0);
  const coverage = Math.max(0, 1 - total_unreached * 4 / total_pop);
  const verified = villages.filter(v => v.has_dhs_data).length / villages.length;
  const hottest = [...villages].sort((a, b) => b.poverty_score - a.poverty_score)[0];

  return {
    tenant_id: tenantId,
    state_label: STATE_NAMES[tenantId] ?? tenantId,
    villages_identified: villages.length,
    population_estimated: total_pop,
    hh_unreached: total_unreached,
    coverage_pct: coverage * 100,
    verification_pct: verified * 100,
    villages,
    hottest_village_id: hottest.id,
  };
}
