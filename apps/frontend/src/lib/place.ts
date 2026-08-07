import { apiFetch, type SuccessEnvelope } from '@/lib/api';
import { TENANTS } from '@/data/tenants';

/**
 * Naming a coordinate, from two sources with different jobs.
 *
 * The LGA and state come from OUR OWN centroid dataset via `/geo/resolve` —
 * 447 geoBoundaries admin-2 units, the same names the alerts, crop-health rows
 * and reports use. That matters more than it sounds: when Mapbox supplied the
 * whole label it could spell an LGA differently from the rest of the platform,
 * and a field officer seeing one place named two ways trusts neither.
 *
 * The town or village comes from Mapbox, which is the only one of the two that
 * knows anything below LGA level.
 *
 * ## Why Mapbox also gets a veto
 *
 * We hold centroids for the ten PILOTS only. So a point just over the border in
 * a non-pilot state has no correct answer in our dataset, and nearest-centroid
 * happily returns the closest pilot unit instead — measured live at
 * (4.60, 11.90), which is Kebbe in SOKOTO: our lookup answered "Jega LGA,
 * Kebbi", 30 km away and in the wrong state. Distance alone cannot catch this,
 * because 30 km is an ordinary distance to a centroid.
 *
 * Mapbox knows every Nigerian state, so its `region` is used as a veto: when it
 * names a state or country that is not the one our lookup landed in, we drop
 * our claim entirely and label the point in Mapbox's own words. Absence of
 * evidence is not contradiction — rural Senegal returns no region at all, and
 * that must leave our (correct) answer standing.
 *
 * ## Accuracy, stated plainly
 *
 * `/geo/resolve` is nearest-centroid, not point-in-polygon. Within a pilot, near
 * an internal LGA boundary, the true containing LGA can still differ from the
 * nearest centroid, and the veto above cannot see that because both LGAs are in
 * the same state. This is a display label and a check-your-coordinates nudge. It
 * should not be persisted as a fact about where a farm is.
 */
export interface ResolvedPlace {
  /** LGA / district, in the platform's own spelling. Null outside coverage. */
  lga: string | null;
  /** Pilot slug the LGA belongs to — compare against the selected pilot. */
  tenantId: string | null;
  /** Kilometres to that unit's centroid; how much to trust `lga`. */
  distanceKm: number | null;
  /** Settlement below LGA level, from Mapbox. Often null in rural areas. */
  town: string | null;
  /** Composed for display, or null when neither source knows anything. */
  label: string | null;
}

const EMPTY: ResolvedPlace = {
  lga: null, tenantId: null, distanceKm: null, town: null, label: null,
};

interface ResolveResponse {
  tenant_id: string | null;
  lga: string | null;
  distance_km: number | null;
}

interface MapboxPlace {
  town: string | null;
  region: string | null;
  country: string | null;
  /** Mapbox's own rendering, e.g. "Sokoto, Nigeria" — used when it vetoes us. */
  formatted: string | null;
}

const NO_MAPBOX: MapboxPlace = {
  town: null, region: null, country: null, formatted: null,
};

/** Our own answer: which administrative unit is this, in our own words. */
async function fetchUnit(lon: number, lat: number): Promise<ResolveResponse> {
  try {
    const env: SuccessEnvelope<ResolveResponse> =
      await apiFetch<ResolveResponse>(`/geo/resolve?lon=${lon}&lat=${lat}`);
    return env.data;
  } catch {
    return { tenant_id: null, lga: null, distance_km: null };
  }
}

/**
 * Mapbox Geocoding **v6**.
 *
 * The move off v5 is what makes this practical: v5 returned one concatenated
 * `place_name` ("Kamba, Dandi, Kebbi, Nigeria") that we would have had to pull
 * apart, whereas v6 exposes the matched feature's own name and a structured
 * `context`, so the settlement and the region can be used for different jobs.
 *
 * `types` is restricted to sub-LGA features on purpose — we never want Mapbox's
 * spelling of an administrative unit we already name ourselves. The region
 * still arrives via `context`, which is what the veto reads.
 */
async function fetchMapboxPlace(lon: number, lat: number): Promise<MapboxPlace> {
  const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
  if (!token) return NO_MAPBOX;
  try {
    const res = await fetch(
      'https://api.mapbox.com/search/geocode/v6/reverse' +
        `?longitude=${lon}&latitude=${lat}` +
        `&types=neighborhood,locality,place&limit=1&access_token=${token}`,
    );
    if (!res.ok) return NO_MAPBOX;
    const j = (await res.json()) as {
      features?: {
        properties?: {
          name?: string;
          name_preferred?: string;
          place_formatted?: string;
          context?: Record<string, { name?: string } | undefined>;
        };
      }[];
    };
    const p = j.features?.[0]?.properties;
    if (!p) return NO_MAPBOX;
    return {
      town: p.name_preferred ?? p.name ?? null,
      region: p.context?.region?.name ?? null,
      country: p.context?.country?.name ?? null,
      formatted: p.place_formatted ?? null,
    };
  } catch {
    return NO_MAPBOX;
  }
}

function norm(s: string): string {
  return s.toLowerCase().replace(/\s+state$/, '').replace(/[^a-z ]/g, '').trim();
}

/** Neither string containing the other counts as disagreement. */
function disagrees(a: string, b: string): boolean {
  const [x, y] = [norm(a), norm(b)];
  if (!x || !y) return false;
  return !x.includes(y) && !y.includes(x);
}

/**
 * Does Mapbox place this point somewhere our lookup did not?
 *
 * Nigerian pilots are checked against `region` (Mapbox knows all 36 states plus
 * "Federal Capital Territory", which matches our own tenant name verbatim);
 * country-level pilots against `country`. Missing data returns false — we only
 * override our own answer on positive evidence.
 */
function mapboxVetoes(mb: MapboxPlace, tenantId: string | null): boolean {
  const tenant = TENANTS.find((t) => t.id === tenantId);
  if (!tenant) return false;
  if (tenant.country === 'nigeria') {
    return mb.region ? disagrees(mb.region, tenant.name) : false;
  }
  return mb.country ? disagrees(mb.country, tenant.name) : false;
}

/**
 * Compose the display label.
 *
 * "LGA" is appended only for Nigerian units — Ghana and Senegal call the same
 * administrative level a district, and labelling Accra's "Ayawaso East
 * Municipal" an LGA would be wrong in a way local users would notice.
 *
 * A town that merely restates the unit is dropped: Mapbox answers "Birnin Kebbi
 * south" inside Birnin Kebbi LGA, and "near Birnin Kebbi south — Birnin Kebbi
 * LGA" reads like a machine talking to itself.
 */
function composeOurs(
  lga: string, tenantId: string, town: string | null,
): string {
  const tenant = TENANTS.find((t) => t.id === tenantId);
  const isNigerian = tenant?.country === 'nigeria';
  const unit = isNigerian && !/\blga\b/i.test(lga) ? `${lga} LGA` : lga;
  const admin = [unit, tenant?.name].filter(Boolean).join(', ');
  // Keep the town only when it actually ADDS something the unit name doesn't.
  const townAddsInformation = town !== null && disagrees(town, lga);
  return townAddsInformation ? `near ${town} — ${admin}` : admin;
}

/** Resolve a coordinate to a display label, both sources in parallel. */
export async function resolvePlace(
  lon: number, lat: number,
): Promise<ResolvedPlace> {
  // Parallel, not sequential: Mapbox is the slower call and nothing depends on it.
  const [unit, mb] = await Promise.all([
    fetchUnit(lon, lat),
    fetchMapboxPlace(lon, lat),
  ]);

  const ourClaimStands =
    unit.lga !== null &&
    unit.tenant_id !== null &&
    !mapboxVetoes(mb, unit.tenant_id);

  if (ourClaimStands) {
    return {
      lga: unit.lga,
      tenantId: unit.tenant_id,
      distanceKm: unit.distance_km,
      town: mb.town,
      label: composeOurs(unit.lga!, unit.tenant_id!, mb.town),
    };
  }

  // Either we know nothing, or Mapbox says we are in the wrong place. Fall back
  // to its wording and make NO administrative claim of our own — a null
  // tenantId also stops pilotMismatch() firing on an answer we don't trust.
  //
  // `place_formatted` often already leads with the town ("Lagos" inside "Lagos,
  // Nigeria"), so prefixing unconditionally would yield "Lagos, Lagos, Nigeria".
  const townLeadsAlready =
    mb.town !== null && mb.formatted !== null &&
    norm(mb.formatted).startsWith(norm(mb.town));
  const fallback = mb.town && mb.formatted && !townLeadsAlready
    ? `${mb.town}, ${mb.formatted}`
    : mb.formatted ?? mb.town;
  if (!fallback) return EMPTY;
  return { ...EMPTY, town: mb.town, label: fallback };
}

/**
 * True when the coordinate lands outside the pilot being viewed — the tell-tale
 * of a mistyped entry (latitude pasted into the longitude box lands a couple of
 * hundred kilometres away).
 *
 * Now a slug comparison. The previous version string-matched Mapbox's place name
 * against the pilot's display name and needed a special case for FCT ("Federal
 * Capital Territory" vs "Abuja"); every naming difference was a potential false
 * alarm or silent miss. Comparing `tenantId` has no such failure mode.
 *
 * An unplaceable point is NOT a mismatch: a point we cannot place is a point we
 * cannot contradict.
 */
export function pilotMismatch(
  place: ResolvedPlace | null, pilotId: string,
): boolean {
  if (!place?.tenantId) return false;
  return place.tenantId !== pilotId;
}
