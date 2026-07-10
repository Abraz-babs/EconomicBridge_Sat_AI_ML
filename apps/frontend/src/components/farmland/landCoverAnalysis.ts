/**
 * In-browser land-cover pixel analytics for the Alert Spotlight (Phase 2).
 *
 * Fetches the Esri/Impact Observatory Sentinel-2 10 m annual classification
 * around a coordinate (keyless exportImage; CORS to our origin verified) and
 * counts class pixels on a hidden canvas → real percentages like
 * "rangeland 86.3% · built 13.2%" and the built-up delta between two years.
 *
 * Deterministic and computed — no model, no estimate. Requested with
 * RSP_NearestNeighbor so class colours arrive unblended (bilinear would
 * smear colours at tile edges and corrupt the counts).
 */

/** Class colours exactly as the service's cartographic renderer emits them
 *  (sampled from live output 2026-07-09). */
export const LULC_CLASSES: { hex: string; rgb: [number, number, number]; label: string }[] = [
  { hex: '#FFDB5C', rgb: [0xff, 0xdb, 0x5c], label: 'crops' },
  { hex: '#ED022A', rgb: [0xed, 0x02, 0x2a], label: 'built' },
  { hex: '#EFCFA8', rgb: [0xef, 0xcf, 0xa8], label: 'rangeland' },
  { hex: '#358221', rgb: [0x35, 0x82, 0x21], label: 'trees' },
  { hex: '#1A5BAB', rgb: [0x1a, 0x5b, 0xab], label: 'water' },
  { hex: '#87D19E', rgb: [0x87, 0xd1, 0x9e], label: 'flooded' },
  { hex: '#EDE9E4', rgb: [0xed, 0xe9, 0xe4], label: 'bare' },
];

export interface LandMix {
  /** label → percent of classified pixels (0–100, 1dp). */
  pct: Record<string, number>;
  /** How many pixels actually carried a known class (coverage sanity). */
  classified: number;
}

export interface LandCoverComparison {
  yearA: number;
  yearB: number;
  mixA: LandMix;
  mixB: LandMix;
  /** built% in yearB − built% in yearA (percentage points, 1dp). */
  builtDeltaPts: number;
  /** Radius the analysis covered, in km (for honest labelling). */
  radiusKm: number;
}

const ANALYSIS_HALF_M = 3000; // ±3 km — matches the Spotlight land thumbs
const SIZE = 200;             // 200×200 = 40k pixels; instant to count

function lulcUrl(lat: number, lon: number, year: number): string {
  const R = 20037508.34;
  const mx = (lon * R) / 180;
  const my = ((Math.log(Math.tan(((90 + lat) * Math.PI) / 360)) / (Math.PI / 180)) * R) / 180;
  const bbox = `${mx - ANALYSIS_HALF_M},${my - ANALYSIS_HALF_M},${mx + ANALYSIS_HALF_M},${my + ANALYSIS_HALF_M}`;
  return (
    'https://ic.imagery1.arcgis.com/arcgis/rest/services/Sentinel2_10m_LandCover/ImageServer/exportImage' +
    `?f=image&bbox=${bbox}&bboxSR=3857&imageSR=3857&size=${SIZE},${SIZE}` +
    `&format=png32&transparent=true&interpolation=RSP_NearestNeighbor` +
    `&time=${Date.UTC(year, 6, 1)}`
  );
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous'; // CORS fetch — the service allows our origin
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('land-cover image failed to load'));
    img.src = src;
  });
}

/** Count class pixels for one year. Returns null when the canvas is tainted,
 *  the service is unreachable, or coverage is essentially empty. */
export async function fetchLandMix(lat: number, lon: number, year: number): Promise<LandMix | null> {
  try {
    const img = await loadImage(lulcUrl(lat, lon, year));
    const canvas = document.createElement('canvas');
    canvas.width = SIZE;
    canvas.height = SIZE;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(img, 0, 0, SIZE, SIZE);
    const { data } = ctx.getImageData(0, 0, SIZE, SIZE);

    const counts = new Map<string, number>();
    let classified = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 200) continue; // transparent = no data
      const r = data[i], g = data[i + 1], b = data[i + 2];
      for (const cls of LULC_CLASSES) {
        // Exact-match with a ±2 tolerance guards against colour-profile drift
        // without ever letting neighbouring classes bleed into each other.
        if (
          Math.abs(r - cls.rgb[0]) <= 2 &&
          Math.abs(g - cls.rgb[1]) <= 2 &&
          Math.abs(b - cls.rgb[2]) <= 2
        ) {
          counts.set(cls.label, (counts.get(cls.label) ?? 0) + 1);
          classified += 1;
          break;
        }
      }
    }
    if (classified < SIZE * SIZE * 0.2) return null; // <20% coverage → don't publish a number

    const pct: Record<string, number> = {};
    for (const [label, n] of counts) pct[label] = Math.round((n / classified) * 1000) / 10;
    return { pct, classified };
  } catch {
    return null;
  }
}

/** Two-year comparison used by the Spotlight card. Null if either year lacks
 *  usable coverage — the UI then falls back to thumbnails only. */
export async function compareLandCover(
  lat: number,
  lon: number,
  yearA = 2018,
  yearB = 2025,
): Promise<LandCoverComparison | null> {
  const [mixA, mixB] = await Promise.all([
    fetchLandMix(lat, lon, yearA),
    fetchLandMix(lat, lon, yearB),
  ]);
  if (!mixA || !mixB) return null;
  const builtDeltaPts =
    Math.round(((mixB.pct.built ?? 0) - (mixA.pct.built ?? 0)) * 10) / 10;
  return { yearA, yearB, mixA, mixB, builtDeltaPts, radiusKm: ANALYSIS_HALF_M / 1000 };
}

/** Top classes of a mix as ordered [label, pct] pairs (for the bars). */
export function topClasses(mix: LandMix, n = 3): [string, number][] {
  return Object.entries(mix.pct)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n);
}

export function classColor(label: string): string {
  return LULC_CLASSES.find((c) => c.label === label)?.hex ?? '#a89f93';
}
