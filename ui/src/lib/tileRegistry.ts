/**
 * The tile-set registry (burndown 8.4): what the Horus tile server serves, read at run
 * time from its /registry.json (docs/TILESETS.md). A new tile file shows up after a
 * tile-server restart, with no UI rebuild.
 */
import { basemapStyleUrl } from './tileProxy';

export interface TileSet {
  id: string;
  kind: 'file' | 'url';
  role: 'basemap' | 'imagery' | 'overlay';
  title: string;
  format: string;
  type: 'raster' | 'vector';
  attribution: string;
  licence: { id: string | null; url: string | null };
  marking: { classification: string | null; releasability: string | null };
  captured: { start: string; end: string } | null;
  bounds: [number, number, number, number];
  minzoom: number;
  maxzoom: number;
  /** Stacking: higher draws on top. The registry lists entries bottom to top. */
  order: number;
}

/** The tile server's base URL, from the basemap style URL (…/styles/dark/style.json). */
export function tileServerBase(styleUrl = basemapStyleUrl()): string {
  const m = styleUrl.match(/^(.*\/)styles\/[^/]+\/style\.json(?:\?.*)?$/);
  return m ? m[1] : new URL('/', styleUrl).toString();
}

/** TileJSON for one served tile file (its tile URL, format, zooms and bounds). */
export function tileJsonUrl(id: string, base = tileServerBase()): string {
  return `${base}data/${encodeURIComponent(id)}.json`;
}

/**
 * The imagery tile files, bottom to top. Empty if the tile server is unreachable or
 * serves none: the satellite view then has nothing of Horus's own to show.
 */
export async function fetchImagery(base = tileServerBase()): Promise<TileSet[]> {
  try {
    const r = await fetch(`${base}registry.json`, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!r.ok) return [];
    const reg = await r.json();
    const sets: TileSet[] = Array.isArray(reg?.tilesets) ? reg.tilesets : [];
    // kind "url" (customer tile servers) comes with 8.6.
    return sets.filter(t => t.role === 'imagery' && t.type === 'raster' && t.kind === 'file');
  } catch {
    return [];
  }
}
