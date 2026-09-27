'use client';

/**
 * The controls above every module map: a map-style switch (Satellite / Dark /
 * Light) and the module's own layer chips. Real buttons with aria-pressed, so
 * both are keyboard- and screen-reader-operable.
 */

import { BASEMAPS, BASEMAP_LABEL, type Basemap } from './basemaps';

export interface MapLayerChip {
  id: string;
  label: string;
  /** Swatch colour shown in the chip. */
  dot: string;
  on: boolean;
}

export default function MapToolbar(props: {
  basemap: Basemap;
  onBasemap: (b: Basemap) => void;
  layers: MapLayerChip[];
  onToggle: (id: string) => void;
  tone?: 'light' | 'dark';
}) {
  const { basemap, onBasemap, layers, onToggle, tone = 'light' } = props;
  return (
    <div className={`mm-toolbar mm-toolbar--${tone}`}>
      <div className="mm-basemaps" role="group" aria-label="Map style">
        {BASEMAPS.map((b) => (
          <button
            key={b}
            type="button"
            className={`mm-basemap ${basemap === b ? 'is-on' : ''}`}
            aria-pressed={basemap === b}
            onClick={() => onBasemap(b)}
          >
            {BASEMAP_LABEL[b]}
          </button>
        ))}
      </div>
      <div className="mm-layers" role="group" aria-label="Map layers">
        {layers.map((l) => (
          <button
            key={l.id}
            type="button"
            className={`mm-chip ${l.on ? 'is-on' : ''}`}
            aria-pressed={l.on}
            onClick={() => onToggle(l.id)}
          >
            <span className="mm-chip-dot" style={{ background: l.dot }} aria-hidden="true" />
            {l.label}
          </button>
        ))}
      </div>
    </div>
  );
}
