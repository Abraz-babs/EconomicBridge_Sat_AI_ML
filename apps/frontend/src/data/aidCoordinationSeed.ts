/**
 * Deterministic-per-tenant seed data for the Aid Coordination Bridge.
 *
 * Real partner-org integrations (WFP SCOPE, UNHCR proGres, NEMA, NGO
 * coordination forums) land in follow-up slices. For now the dashboard
 * renders demo data hashed from the tenant slug.
 */

const AGENCY_POOL = [
  { id: 'wfp',         name: 'World Food Programme',         sector: 'food security'    },
  { id: 'unhcr',       name: 'UNHCR',                         sector: 'displacement'     },
  { id: 'unicef',      name: 'UNICEF',                        sector: 'child welfare'    },
  { id: 'red_cross',   name: 'Nigerian Red Cross',            sector: 'emergency relief' },
  { id: 'nema',        name: 'NEMA',                          sector: 'disaster relief'  },
  { id: 'msf',         name: 'Médecins Sans Frontières',      sector: 'medical'          },
  { id: 'save_kids',   name: 'Save the Children',             sector: 'child welfare'    },
  { id: 'oxfam',       name: 'Oxfam',                         sector: 'food security'    },
  { id: 'mercy',       name: 'Mercy Corps',                   sector: 'livelihoods'      },
  { id: 'norwegian',   name: 'Norwegian Refugee Council',     sector: 'displacement'     },
];

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

const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
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


export interface AgencyCoverage {
  agency_id: string;
  agency_name: string;
  sector: string;
  lgas_covered: string[];
  beneficiaries_served: number;  // estimate
}

export interface LgaPoint {
  lga: string;
  lon: number;
  lat: number;
  /** Number of agencies operating in this LGA. */
  agency_count: number;
  /** `gap` (0 agencies) | `covered` (1) | `duplicated` (2+). */
  status: 'gap' | 'covered' | 'duplicated';
  /** Names of agencies present (empty when status='gap'). */
  agency_ids: string[];
}

export interface CoordinationStats {
  tenant_id: string;
  state_label: string;
  active_agencies: number;
  total_lgas: number;
  covered_lgas: number;
  coverage_pct: number;
  duplication_pct: number;     // % of LGAs with 2+ agencies in same sector
  gap_lgas: string[];          // LGAs with no agency
  agencies: AgencyCoverage[];
  /** Matrix: rows = agencies, cols = LGAs. value = 0 (off) or 1 (covered) */
  matrix: { agency_id: string; agency_name: string; row: number[] }[];
  lga_columns: string[];
  /** Per-LGA centroids (jittered around tenant centroid) for the map. */
  lga_points: LgaPoint[];
}


export function coordinationStatsFor(
  tenantId: string,
  centroid: [number, number] = [0, 0],
): CoordinationStats {
  const lgas = LGA_POOL[tenantId] ?? [`${tenantId} Region 1`, `${tenantId} Region 2`];
  const r = rng(hashString(tenantId));

  // Pick 5..8 agencies for this tenant
  const agencyCount = 5 + Math.floor(r() * 4);
  const shuffled = [...AGENCY_POOL].sort((a, b) => {
    return hashString(tenantId + a.id) - hashString(tenantId + b.id);
  });
  const picked = shuffled.slice(0, agencyCount);

  const agencies: AgencyCoverage[] = [];
  for (const a of picked) {
    // Each agency covers 2..5 LGAs
    const lgaCount = 2 + Math.floor(r() * 4);
    const covered: string[] = [];
    for (let i = 0; i < lgaCount && i < lgas.length; i++) {
      const idx = Math.floor(r() * lgas.length);
      if (!covered.includes(lgas[idx])) covered.push(lgas[idx]);
    }
    agencies.push({
      agency_id: a.id,
      agency_name: a.name,
      sector: a.sector,
      lgas_covered: covered,
      beneficiaries_served: 1_500 + Math.floor(r() * 18_000),
    });
  }

  // Coverage + duplication analysis
  const lga_to_agencies: Record<string, string[]> = {};
  for (const lga of lgas) lga_to_agencies[lga] = [];
  for (const a of agencies) {
    for (const lga of a.lgas_covered) {
      if (!lga_to_agencies[lga]) lga_to_agencies[lga] = [];
      lga_to_agencies[lga].push(a.agency_id);
    }
  }
  const covered_lgas = Object.values(lga_to_agencies).filter(v => v.length > 0).length;
  const dup_lgas = Object.values(lga_to_agencies).filter(v => v.length > 1).length;
  const gap_lgas = Object.entries(lga_to_agencies)
    .filter(([, v]) => v.length === 0)
    .map(([k]) => k);

  // Build matrix
  const matrix = agencies.map(a => ({
    agency_id: a.agency_id,
    agency_name: a.agency_name,
    row: lgas.map(lga => a.lgas_covered.includes(lga) ? 1 : 0),
  }));

  // LGA centroids deterministically jittered around tenant centroid.
  // Real LGA polygons land with the Module 02 real-data slice; for now
  // this gives the map a clear visual story per tenant.
  const lga_points: LgaPoint[] = lgas.map((lga, idx) => {
    // 8-direction spiral pattern using LGA index so points fan out
    // around the tenant centre.
    const angle = (idx * 360 / lgas.length) * Math.PI / 180;
    const radius = 0.45 + (idx % 3) * 0.18;
    const lon = centroid[0] + Math.cos(angle) * radius;
    const lat = centroid[1] + Math.sin(angle) * radius * 0.85;
    const count = lga_to_agencies[lga]?.length ?? 0;
    const status: LgaPoint['status'] =
      count === 0 ? 'gap' : count === 1 ? 'covered' : 'duplicated';
    return {
      lga, lon, lat,
      agency_count: count,
      status,
      agency_ids: lga_to_agencies[lga] ?? [],
    };
  });

  return {
    tenant_id: tenantId,
    state_label: STATE_NAMES[tenantId] ?? tenantId,
    active_agencies: agencies.length,
    total_lgas: lgas.length,
    covered_lgas,
    coverage_pct: (covered_lgas / lgas.length) * 100,
    duplication_pct: (dup_lgas / lgas.length) * 100,
    gap_lgas,
    agencies,
    matrix,
    lga_columns: lgas,
    lga_points,
  };
}
