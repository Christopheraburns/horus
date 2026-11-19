'use client';

import { useEffect, useRef, useState, useCallback, memo } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  basemapStyleUrl,
  OPENFREEMAP_DARK_STYLE,
  transformBasemapRequest,
} from '@/lib/tileProxy';

// Positions older than this are drawn faded and marked STALE in popups. The
// gateway removes them entirely later (aircraft 25 min, moving ships 20 min,
// ships at anchor 60 min).
const STALE_AFTER_S = 900;

/** Seconds since Horus last heard from an entity, or null when unknown. */
function ageSeconds(item: any): number | null {
  if (typeof item?.age_s === 'number') return item.age_s;           // from the gateway (PIPELINE)
  const ts = item?.timestamp;                                          // PUBLIC: when the UI received it
  return typeof ts === 'number' && ts > 0 ? Math.max(0, Math.round((Date.now() - ts) / 1000)) : null;
}

/** "42 s ago", "7 min ago", "1 h 5 min ago", with a STALE tag past STALE_AFTER_S. */
function ageLabel(age: unknown): string {
  const s = typeof age === 'number' ? age : Number(age);
  if (age === null || age === undefined || age === '' || !Number.isFinite(s)) return '—';
  const text = s < 60 ? `${Math.round(s)} s ago`
    : s < 3600 ? `${Math.round(s / 60)} min ago`
    : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min ago`;
  return s > STALE_AFTER_S ? `${text} · STALE` : text;
}

/** MapLibre expression: true when a feature's age_s is past STALE_AFTER_S. */
const IS_STALE: any = ['>', ['coalesce', ['get', 'age_s'], 0], STALE_AFTER_S];

interface HorusMapProps {
  /** False in PIPELINE mode: never fall back to a public basemap. */
  allowPublicTiles?: boolean;
  data: any;
  activeLayers: Record<string, boolean>;
  onEntityClick?: (entity: any) => void;
  onMouseCoords?: (coords: { lat: number; lng: number }) => void;
  onRightClick?: (coords: { lat: number; lng: number }) => void;
  onViewStateChange?: (vs: { zoom: number; latitude: number }) => void;
  flyToLocation?: { lat: number; lng: number; zoom?: number; ts: number } | null;
  projection?: 'mercator' | 'globe';
  mapStyle?: string;
  demoMode?: boolean;
  timeTravelActive?: boolean;
  timeTravelFrame?: { asset_id: string; asset_type: string; lat: number; lng: number; t: number; name?: string }[];
}

function computeSolarTerminator(): [number, number][] {
  const now = new Date();
  const dayOfYear = Math.floor((now.getTime() - new Date(now.getFullYear(), 0, 0).getTime()) / 86400000);
  const declination = -23.44 * Math.cos((2 * Math.PI / 365) * (dayOfYear + 10));
  const decRad = declination * Math.PI / 180;
  const utcHours = now.getUTCHours() + now.getUTCMinutes() / 60;
  const subsolarLng = (12 - utcHours) * 15;
  const points: [number, number][] = [];
  for (let lng = -180; lng <= 180; lng += 2) {
    const lngRad = (lng - subsolarLng) * Math.PI / 180;
    const lat = Math.atan(-Math.cos(lngRad) / Math.tan(decRad)) * 180 / Math.PI;
    points.push([lng, lat]);
  }
  const darkSide = declination >= 0 ? -90 : 90;
  points.push([180, darkSide]);
  points.push([-180, darkSide]);
  points.push(points[0]);
  return points;
}

const EMPTY_FC = { type: 'FeatureCollection' as const, features: [] };

function HorusMap({ data, activeLayers, onEntityClick, onMouseCoords, onRightClick, onViewStateChange, flyToLocation, projection = 'globe', mapStyle = 'dark', demoMode = false, timeTravelActive = false, timeTravelFrame = [], allowPublicTiles = true }: HorusMapProps) {
  // Read inside the map's one-time error handler, so keep the latest value in a ref.
  const allowPublicTilesRef = useRef(allowPublicTiles);
  allowPublicTilesRef.current = allowPublicTiles;
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const prevStyleRef = useRef(mapStyle);

  // Create aircraft icon on canvas (for WebGL symbol layer)
  const createIcon = useCallback((map: maplibregl.Map, id: string, color: string, size: number) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const cx = size / 2, cy = size / 2;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, cy - size * 0.4);
    ctx.lineTo(cx - size * 0.12, cy + size * 0.1);
    ctx.lineTo(cx - size * 0.4, cy + size * 0.2);
    ctx.lineTo(cx - size * 0.4, cy + size * 0.3);
    ctx.lineTo(cx - size * 0.12, cy + size * 0.15);
    ctx.lineTo(cx, cy + size * 0.35);
    ctx.lineTo(cx + size * 0.12, cy + size * 0.15);
    ctx.lineTo(cx + size * 0.4, cy + size * 0.3);
    ctx.lineTo(cx + size * 0.4, cy + size * 0.2);
    ctx.lineTo(cx + size * 0.12, cy + size * 0.1);
    ctx.closePath();
    ctx.fill();
    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  const createDot = useCallback((map: maplibregl.Map, id: string, color: string, size: number) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(size/2, size/2, size/2 - 1, 0, Math.PI * 2);
    ctx.fill();
    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  // Fire marker: a small flame, drawn here so it needs no image files (air-gap safe).
  // Paths are in a 32-unit box, drawn at 2x for sharp edges on high-DPI screens.
  const createFlame = useCallback((map: maplibregl.Map, id: string) => {
    if (map.hasImage(id)) return;
    const px = 64;
    const canvas = document.createElement('canvas');
    canvas.width = px; canvas.height = px;
    const ctx = canvas.getContext('2d')!;
    ctx.scale(px / 32, px / 32);
    const outer = new Path2D();
    outer.moveTo(16, 2);
    outer.bezierCurveTo(19, 9, 27, 13, 27, 21);
    outer.bezierCurveTo(27, 27.5, 22, 31, 16, 31);
    outer.bezierCurveTo(10, 31, 5, 27.5, 5, 21);
    outer.bezierCurveTo(5, 16, 8, 13, 10, 10);
    outer.bezierCurveTo(10.5, 13, 11.5, 15, 13, 16);
    outer.bezierCurveTo(13, 11, 14, 6, 16, 2);
    outer.closePath();
    const og = ctx.createLinearGradient(0, 2, 0, 31);
    og.addColorStop(0, '#FF7A1A'); og.addColorStop(1, '#E3260B');
    ctx.fillStyle = og; ctx.fill(outer);
    ctx.strokeStyle = 'rgba(0,0,0,0.35)'; ctx.lineWidth = 0.8; ctx.stroke(outer);
    const inner = new Path2D();
    inner.moveTo(16, 14);
    inner.bezierCurveTo(18, 18, 22, 20, 22, 24.5);
    inner.bezierCurveTo(22, 28, 19.5, 30, 16, 30);
    inner.bezierCurveTo(12.5, 30, 10, 28, 10, 24.5);
    inner.bezierCurveTo(10, 21, 13, 19, 16, 14);
    inner.closePath();
    const ig = ctx.createLinearGradient(0, 14, 0, 30);
    ig.addColorStop(0, '#FFE27A'); ig.addColorStop(1, '#FFB300');
    ctx.fillStyle = ig; ctx.fill(inner);
    map.addImage(id, { width: px, height: px, data: new Uint8Array(ctx.getImageData(0, 0, px, px).data) },
                 { pixelRatio: px / 32 });
  }, []);

  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    // ── DEMO MODE SPINNING ──
    let spinReq: number | undefined = undefined;
    let isSpinning = false;
    
    const startSpinning = () => {
      if (!map) return;
      isSpinning = true;
      let lastTime = performance.now();
      
      const frame = (time: number) => {
        if (!isSpinning) return;
        
        // Only spin if the user is not actively dragging or zooming the map
        if (!map.isMoving() && !map.isZooming()) {
          const dt = time - lastTime;
          const center = map.getCenter();
          // Adjust spin speed: 0.5 degrees per second
          center.lng += (0.5 * dt) / 1000;
          map.setCenter(center);
        }
        
        lastTime = time;
        spinReq = requestAnimationFrame(frame);
      };
      
      spinReq = requestAnimationFrame(frame);
    };

    if (demoMode) {
      startSpinning();
    } else {
      isSpinning = false;
      if (spinReq) cancelAnimationFrame(spinReq);
    }

    return () => {
      isSpinning = false;
      if (spinReq) cancelAnimationFrame(spinReq);
      if (typeof window !== 'undefined' && (window as any)._globeSpinTimer) {
        clearInterval((window as any)._globeSpinTimer);
      }
    };
  }, [mapReady, demoMode]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    let fallbackApplied = false;

    const styleUrl = basemapStyleUrl();

    // MapLibre 6: load the worker Horus serves itself (tools/prepare-map-worker.mjs).
    maplibregl.setWorkerUrl(`/vendor/maplibre/${maplibregl.getVersion()}/maplibre-gl-worker.mjs`);
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: styleUrl,
      // Open on the whole globe. (Upstream OSIRIS opened zoomed in on Bulgaria and
      // relied on an IP fly-to, which Horus disables.)
      center: [10, 25], zoom: 1.8, minZoom: 1.5, maxZoom: 18,
      attributionControl: false,
      maxPitch: 85,
      transformRequest: (url: string) => transformBasemapRequest(url),
    });

    map.on('error', (e) => {
      if (fallbackApplied) return;
      const msg = e.error?.message ?? '';
      if (!msg.includes('Failed to fetch') && !msg.includes('404') && !msg.includes('NetworkError')) return;
      if (!allowPublicTilesRef.current) {
        // PIPELINE mode: stay on the Horus tile server; never call OpenFreeMap.
        console.warn('[HORUS] Horus tile server unreachable; no public fallback in PIPELINE mode');
        return;
      }
      fallbackApplied = true;
      console.warn('[HORUS] Local basemap failed; switching to OpenFreeMap fallback');
      map.setStyle(OPENFREEMAP_DARK_STYLE);
    });

    map.on('load', () => {
      mapRef.current = map;
      
      // Theme colors
      const cameraColor = '#00E676';
      const flightCom = '#00E5FF';
      const flightPriv = '#FFD700';
      const flightGov = '#FF9500';
      const flightMil = '#FF0000';

      // Create icons — HORUS Unified Palette
      createIcon(map, 'plane-cyan', flightCom, 24);   
      createIcon(map, 'plane-green', flightPriv, 24);   
      createIcon(map, 'plane-pink', flightGov, 24);    
      createIcon(map, 'plane-red', flightMil, 24);     
      createIcon(map, 'plane-grey', '#546E7A', 24);
      // Aircraft carrying an ICAO airline designator (airline_code) are graph-enrichable
      // — render them in a distinct royal blue (theme-independent marker).
      createIcon(map, 'plane-enrich', '#448AFF', 24);
      // TimeTravel historical aircraft — amber plane icon (matches the replay palette).
      createIcon(map, 'plane-amber', '#FFCA28', 24);
      createDot(map, 'dot-gold', '#D4AF37', 8);
      createDot(map, 'dot-red', '#D32F2F', 10);
      createDot(map, 'dot-orange', '#E65100', 10);
      createDot(map, 'dot-green', '#26A69A', 10);
      createFlame(map, 'fire-flame');
      createDot(map, 'dot-cctv', cameraColor, 10);

      const sources = ['flights','military','jets','private-fl','satellites','earthquakes','gdelt','gps-jamming','day-night','cctv','fires','weather','infrastructure','maritime','maritime-choke','maritime-ships','live-news','sigint-news','conflict-zones', 'war-alerts-targets', 'war-alerts-lines', 'balloons', 'radiation', 'malware-nodes', 'network-mesh', 'timetravel'];
      sources.forEach(s => map.addSource(s, { type: 'geojson', data: EMPTY_FC }));

      // Warning icon generator (parameterized — eliminates 3x copy-paste)
      const createWarningIcon = (id: string, color: string) => {
        const s = 20;
        const c = document.createElement('canvas');
        c.width = s; c.height = s;
        const ctx = c.getContext('2d')!;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(s/2, 1);
        ctx.lineTo(s - 1, s - 1);
        ctx.lineTo(1, s - 1);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = '#000';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('!', s/2, s - 4);
        map.addImage(id, { width: s, height: s, data: new Uint8Array(ctx.getImageData(0, 0, s, s).data) });
      };
      createWarningIcon('warn-icon', '#D32F2F');
      createWarningIcon('warn-orange', '#E65100');
      createWarningIcon('warn-yellow', '#F9A825');

      map.addLayer({ id: 'conflict-icons', type: 'symbol', source: 'conflict-zones', layout: {
        'icon-image': ['match', ['get','severity'], 'war','warn-icon', 'high','warn-orange', 'warn-yellow'],
        'icon-size': ['interpolate',['linear'],['zoom'], 1,0.6, 4,0.8, 8,1],
        'icon-allow-overlap': true,
        'text-field': ['get','label'],
        'text-size': ['interpolate',['linear'],['zoom'], 1,7, 4,9, 8,11],
        'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.4],
        'text-allow-overlap': false,
      }, paint: {
        'text-color': ['match', ['get','severity'], 'war','#D32F2F', 'high','#E65100', '#F9A825'],
        'text-halo-color': '#000', 'text-halo-width': 1.5, 'text-opacity': 0.9,
      }});


      // Day/Night
      map.addLayer({ id: 'day-night-fill', type: 'fill', source: 'day-night', paint: { 'fill-color': '#000022', 'fill-opacity': 0.35 }});

      // Earthquakes — amber threat spectrum
      map.addLayer({ id: 'eq-circles', type: 'circle', source: 'earthquakes', paint: {
        'circle-radius': ['interpolate',['linear'],['get','magnitude'], 2.5,4, 5,12, 7,24],
        'circle-color': ['interpolate',['linear'],['get','magnitude'], 2.5,'#F9A825', 4,'#E65100', 6,'#D32F2F'],
        'circle-opacity': 0.55, 'circle-blur': 0.3, 'circle-stroke-width': 1, 'circle-stroke-color': '#F9A825', 'circle-stroke-opacity': 0.25,
      }});
      map.addLayer({ id: 'eq-label', type: 'symbol', source: 'earthquakes', filter: ['>=',['get','magnitude'],4.5], layout: {
        'text-field': ['concat','M',['to-string',['get','magnitude']]], 'text-size': 9, 'text-font': ['Noto Sans Regular'], 'text-offset': [0,1.5],
      }, paint: { 'text-color': '#F9A825', 'text-halo-color': '#000', 'text-halo-width': 1 }});

      // Fires — a flame icon, so they don't read as the orange vessel dots
      map.addLayer({ id: 'fires-heat', type: 'symbol', source: 'fires', layout: {
        'icon-image': 'fire-flame',
        'icon-size': ['interpolate',['linear'],['zoom'], 1,0.3, 5,0.5, 10,0.8],
        'icon-allow-overlap': true, 'icon-ignore-placement': true,
      }});

      // CCTV — outer glow ring (black/white depending on theme)
      map.addLayer({ id: 'cctv-glow', type: 'circle', source: 'cctv', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,5, 5,8, 10,14, 14,20],
        'circle-color': '#000000', 'circle-opacity': 0.35, 'circle-blur': 1,
      }});
      // CCTV — main dot
      map.addLayer({ id: 'cctv-dots', type: 'circle', source: 'cctv', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,3, 5,5, 10,8, 14,12],
        'circle-color': cameraColor, 'circle-opacity': 0.9,
        'circle-stroke-width': 2.5, 'circle-stroke-color': '#000000', 'circle-stroke-opacity': 0.9,
      }});
      // CCTV — labels at zoom 10+
      map.addLayer({ id: 'cctv-label', type: 'symbol', source: 'cctv', minzoom: 10, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.8], 'text-max-width': 12, 'text-allow-overlap': false,
      }, paint: { 'text-color': cameraColor, 'text-halo-color': '#000000', 'text-halo-width': 1.5, 'text-opacity': 0.8 }});

      // GDELT



      // ══ NETWORK INTEL — Live Malware (abuse.ch) — crimson threat ══
      map.addLayer({ id: 'malware-glow', type: 'circle', source: 'malware-nodes', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,6, 5,12, 10,20],
        'circle-color': '#D32F2F', 'circle-opacity': 0.06, 'circle-blur': 0.5,
      }});
      map.addLayer({ id: 'malware-dots', type: 'circle', source: 'malware-nodes', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,2, 5,4, 10,6],
        'circle-color': '#D32F2F',
        'circle-opacity': 0.9,
        'circle-stroke-width': 1, 'circle-stroke-color': '#000000', 'circle-stroke-opacity': 0.8,
      }});
      map.addLayer({ id: 'malware-label', type: 'symbol', source: 'malware-nodes', minzoom: 5, layout: {
        'text-field': ['get','malware'], 'text-size': 8, 'text-font': ['JetBrains Mono Bold', 'Noto Sans Regular'],
        'text-offset': [0, 1.5], 'text-max-width': 10, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#D32F2F', 'text-halo-color': '#111', 'text-halo-width': 1.5, 'text-opacity': 0.85 }});

      // ── NETWORK INTEL MESH ──
      map.addLayer({ id: 'network-mesh-atmo', type: 'line', source: 'network-mesh', paint: {

        'line-width': ['interpolate',['linear'],['zoom'], 1, 2, 5, 4, 10, 8],
        'line-opacity': 0.08,
        'line-blur': 4,
      }});
      map.addLayer({ id: 'network-mesh-glow', type: 'line', source: 'network-mesh', paint: {

        'line-width': ['interpolate',['linear'],['zoom'], 1, 1, 5, 2, 10, 4],
        'line-opacity': 0.2,
        'line-blur': 1.5,
      }});
      map.addLayer({ id: 'network-mesh-core', type: 'line', source: 'network-mesh', paint: {

        'line-width': ['interpolate',['linear'],['zoom'], 1, 0.2, 5, 0.5, 10, 1.5],
        'line-opacity': 0.4,
      }});


      map.addLayer({ id: 'gdelt-dots', type: 'circle', source: 'gdelt', paint: {
        'circle-radius': 4, 'circle-color': '#D32F2F', 'circle-opacity': 0.5, 'circle-stroke-width': 1, 'circle-stroke-color': '#D32F2F', 'circle-stroke-opacity': 0.25,
      }});

      // GPS Jamming — crimson
      map.addLayer({ id: 'jam-fill', type: 'circle', source: 'gps-jamming', paint: { 'circle-radius': 30, 'circle-color': '#D32F2F', 'circle-opacity': 0.12, 'circle-blur': 1 }});
      map.addLayer({ id: 'jam-label', type: 'symbol', source: 'gps-jamming', layout: {
        'text-field': ['concat','GPS JAM ',['to-string',['get','severity']],'%'], 'text-size': 10, 'text-font': ['Noto Sans Regular'], 'text-allow-overlap': true,
      }, paint: { 'text-color': '#D32F2F', 'text-halo-color': '#000', 'text-halo-width': 1 }});

      // Weather Events (NASA EONET) — deep violet
      map.addLayer({ id: 'weather-glow', type: 'circle', source: 'weather', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,12, 5,20, 10,30],
        'circle-color': '#7E57C2', 'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'weather-dots', type: 'circle', source: 'weather', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,5, 5,8, 10,14],
        'circle-color': ['match', ['get','icon'], 'cyclone','#7E57C2', 'volcano','#D32F2F', '#7E57C2'],
        'circle-opacity': 0.75,
        'circle-stroke-width': 1.5, 'circle-stroke-color': '#7E57C2', 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'weather-label', type: 'symbol', source: 'weather', layout: {
        'text-field': ['get','title'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 2], 'text-max-width': 14, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#7E57C2', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.8 }});

      // Nuclear Infrastructure — teal / amber risk
      map.addLayer({ id: 'infra-glow', type: 'circle', source: 'infrastructure', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,8, 5,14, 10,22],
        'circle-color': ['case', ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100', '#26A69A'],
        'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'infra-dots', type: 'circle', source: 'infrastructure', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,6, 10,10],
        'circle-color': ['case', 
          ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100',
          ['==', ['get','status'], 'Active Conflict Zone'], '#D32F2F', 
          ['==', ['get','status'], 'Destroyed / Decommissioning'], '#546E7A', 
          '#26A69A'
        ],
        'circle-opacity': 0.75,
        'circle-stroke-width': 1.5, 'circle-stroke-color': ['case', ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100', '#26A69A'], 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'infra-label', type: 'symbol', source: 'infrastructure', minzoom: 5, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 2], 'text-max-width': 14, 'text-allow-overlap': false,
      }, paint: { 'text-color': ['case', ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100', '#26A69A'], 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.7 }});

      // Satellites
      map.addLayer({ id: 'sat-glow', type: 'circle', source: 'satellites', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,3, 5,6], 'circle-color': ['get','color'], 'circle-opacity': 0.3, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'sat-dots', type: 'circle', source: 'satellites', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,1.5, 5,3], 'circle-color': ['get','color'], 'circle-opacity': 1.0,
      }});

      // Maritime — ports & naval bases — ocean teal
      map.addLayer({ id: 'maritime-glow', type: 'circle', source: 'maritime', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,6, 5,12, 10,20],
        'circle-color': ['match', ['get','type'], 'naval','#D32F2F', 'energy','#E65100', '#26C6DA'],
        'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'maritime-dots', type: 'circle', source: 'maritime', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,3, 5,5, 10,9],
        'circle-color': ['match', ['get','type'], 'naval','#D32F2F', 'energy','#E65100', '#26C6DA'],
        'circle-opacity': 0.8,
        'circle-stroke-width': 1.5, 'circle-stroke-color': ['match', ['get','type'], 'naval','#D32F2F', 'energy','#E65100', '#26C6DA'], 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'maritime-label', type: 'symbol', source: 'maritime', minzoom: 4, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.8], 'text-max-width': 12, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#26C6DA', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.7 }});

      // Maritime chokepoints — amber threat spectrum
      map.addLayer({ id: 'choke-glow', type: 'circle', source: 'maritime-choke', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,10, 5,18, 10,28],
        'circle-color': '#E65100', 'circle-opacity': 0.1, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'choke-dots', type: 'circle', source: 'maritime-choke', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,7, 10,12],
        'circle-color': ['match', ['get','risk'], 'CRITICAL','#D32F2F', 'HIGH','#E65100', 'ELEVATED','#F9A825', '#26A69A'],
        'circle-opacity': 0.85,
        'circle-stroke-width': 1.5, 'circle-stroke-color': '#E65100', 'circle-stroke-opacity': 0.4,
      }});
      map.addLayer({ id: 'choke-label', type: 'symbol', source: 'maritime-choke', minzoom: 3, layout: {
        'text-field': ['get','name'], 'text-size': 10, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 2], 'text-max-width': 14, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#E65100', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.9 }});

      // Live News — muted rose
      map.addLayer({ id: 'news-glow', type: 'circle', source: 'live-news', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,8, 5,14, 10,22],
        'circle-color': '#EC407A', 'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'news-dots', type: 'circle', source: 'live-news', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,6, 10,10],
        'circle-color': '#EC407A', 'circle-opacity': 0.8,
        'circle-stroke-width': 1.5, 'circle-stroke-color': '#EC407A', 'circle-stroke-opacity': 0.4,
      }});
      map.addLayer({ id: 'news-label', type: 'symbol', source: 'live-news', minzoom: 4, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.8], 'text-max-width': 12, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#EC407A', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.8 }});

      // SIGINT RSS news - gold markers
      map.addLayer({ id: 'sigint-news-glow', type: 'circle', source: 'sigint-news', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,6, 5,10, 10,18],
        'circle-color': '#D4AF37', 'circle-opacity': 0.12, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'sigint-news-dots', type: 'circle', source: 'sigint-news', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,3, 5,5, 10,8],
        'circle-color': '#D4AF37', 'circle-opacity': 0.9,
        'circle-stroke-width': 1.5, 'circle-stroke-color': '#FFF8DC', 'circle-stroke-opacity': 0.6,
      }});
      map.addLayer({ id: 'sigint-news-label', type: 'symbol', source: 'sigint-news', minzoom: 5, layout: {
        'text-field': ['get','source'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.6], 'text-max-width': 10, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#D4AF37', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.85 }});

      // Flight layers (WebGL symbol — GPU rendered, handles 50K+ smooth)
      const flightLayers = [
        { id: 'fl-commercial', src: 'flights', icon: 'plane-cyan' },
        { id: 'fl-private', src: 'private-fl', icon: 'plane-green' },
        { id: 'fl-jets', src: 'jets', icon: 'plane-pink' },
        { id: 'fl-military', src: 'military', icon: 'plane-red' },
      ];
      flightLayers.forEach(l => {
        // Aircraft with an ICAO airline designator (airline_code) are graph-enrichable →
        // distinct royal-blue plane. Military keeps its threat-red icon.
        const iconImage: any = l.id === 'fl-military'
          ? l.icon
          : ['case', ['==', ['get', 'has_airline'], true], 'plane-enrich', l.icon];
        map.addLayer({ id: l.id, type: 'symbol', source: l.src, layout: {
          'icon-image': iconImage, 'icon-size': ['interpolate',['linear'],['zoom'], 1,0.4, 5,0.7, 10,1],
          'icon-rotate': ['get','heading'], 'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-ignore-placement': true,
        }, paint: { 'icon-opacity': ['case', IS_STALE, 0.3, 0.85] }});
      });

      // Balloons (moving entities)
      map.addLayer({ id: 'balloon-dots', type: 'circle', source: 'balloons', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,3, 5,5, 10,7],
        'circle-color': ['get', 'color'],
        'circle-opacity': 0.8,
        'circle-stroke-width': 1, 'circle-stroke-color': '#fff', 'circle-stroke-opacity': 0.5,
      }});
      map.addLayer({ id: 'balloon-label', type: 'symbol', source: 'balloons', minzoom: 4, layout: {
        'text-field': ['get','callsign'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.2], 'text-max-width': 12, 'text-allow-overlap': false,
      }, paint: { 'text-color': ['get', 'color'], 'text-halo-color': '#000', 'text-halo-width': 1 }});

      // Radiation — violet base, threat spectrum for danger/warning
      map.addLayer({ id: 'rad-glow', type: 'circle', source: 'radiation', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,10, 5,20, 10,40],
        'circle-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'],
        'circle-opacity': 0.12, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'rad-dots', type: 'circle', source: 'radiation', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,6, 10,8],
        'circle-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'],
        'circle-opacity': 0.85,
        'circle-stroke-width': 1.5, 'circle-stroke-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'], 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'rad-label', type: 'symbol', source: 'radiation', minzoom: 5, layout: {
        'text-field': ['concat', ['to-string', ['get','reading']], ' nSv/h'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.5], 'text-allow-overlap': false,
      }, paint: { 'text-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'], 'text-halo-color': '#000', 'text-halo-width': 1 }});

      // TimeTravel replay entities. Aircraft render as a yellow plane icon (matching
      // the live symbology); vessels/other keep the amber "historical" halo + dot.
      map.addLayer({ id: 'tt-glow', type: 'circle', source: 'timetravel',
        filter: ['!=', ['get','domain'], 'AIR'], paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,5, 5,9, 10,16],
        'circle-color': '#FFB300', 'circle-opacity': 0.10, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'tt-dots', type: 'circle', source: 'timetravel',
        filter: ['!=', ['get','domain'], 'AIR'], paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,2.5, 5,4.5, 10,7],
        'circle-color': ['match', ['get','domain'], 'SEA','#4FC3F7', '#FFB300'],
        'circle-opacity': 0.9,
        'circle-stroke-width': 1, 'circle-stroke-color': '#FFB300', 'circle-stroke-opacity': 0.5,
      }});
      map.addLayer({ id: 'tt-planes', type: 'symbol', source: 'timetravel',
        filter: ['==', ['get','domain'], 'AIR'], layout: {
        'icon-image': 'plane-amber',
        'icon-size': ['interpolate',['linear'],['zoom'], 1,0.4, 5,0.7, 10,1],
        'icon-allow-overlap': true,
      }});
      map.addLayer({ id: 'tt-label', type: 'symbol', source: 'timetravel', minzoom: 5, layout: {
        'text-field': ['get','label'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.2], 'text-allow-overlap': false,
      }, paint: { 'text-color': '#FFCA28', 'text-halo-color': '#000', 'text-halo-width': 1 }});

      // Maritime Ships (moving entities) — ocean teal family
      map.addLayer({ id: 'ship-dots', type: 'circle', source: 'maritime-ships', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,2, 5,4, 10,6],
        // IMO-bearing vessels (graph-enrichable) get a distinct royal blue so they
        // stand out at a glance; military/tanker keep their threat colors.
        'circle-color': ['case',
          ['==', ['get','type'], 'military'], '#D32F2F',
          ['==', ['get','type'], 'tanker'], '#E65100',
          ['==', ['get','has_imo'], true], '#448AFF',
          ['==', ['get','type'], 'cargo'], '#26C6DA',
          '#B0BEC5'],
        'circle-opacity': ['case', IS_STALE, 0.25, 0.75],
      }});
      map.addLayer({ id: 'ship-label', type: 'symbol', source: 'maritime-ships', minzoom: 5, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Noto Sans Regular'],
        'text-offset': [0, 1.2], 'text-allow-overlap': false,
      }, paint: { 'text-color': ['case',
          ['==', ['get','type'], 'military'], '#D32F2F',
          ['==', ['get','type'], 'tanker'], '#E65100',
          ['==', ['get','has_imo'], true], '#448AFF',
          ['==', ['get','type'], 'cargo'], '#26C6DA',
          '#B0BEC5'], 'text-halo-color': '#000', 'text-halo-width': 1,
        'text-opacity': ['case', IS_STALE, 0.35, 1] }});

      setMapReady(true);
    });

    // Events
    let lastMove = 0;
    map.on('mousemove', e => {
      const now = Date.now();
      if (now - lastMove > 100) {
        lastMove = now;
        onMouseCoords?.({ lat: e.lngLat.lat, lng: e.lngLat.lng });
      }
    });
    map.on('contextmenu', e => { e.preventDefault(); onRightClick?.({ lat: e.lngLat.lat, lng: e.lngLat.lng }); });
    map.on('moveend', () => { const c = map.getCenter(); onViewStateChange?.({ zoom: map.getZoom(), latitude: c.lat }); });

    // ── POPUP HELPER ──
    const popup = (coords: any, html: string) => {
      popupRef.current?.remove();
      popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '420px', offset: 14 }).setLngLat(coords).setHTML(html).addTo(map);
    };
    const pStyle = `background:rgba(12,14,26,0.95);backdrop-filter:blur(16px);border-radius:10px;padding:16px;font-family:'JetBrains Mono',monospace;`;

    // ── XSS PROTECTION HELPERS ──
    const htmlEsc = (s: any): string => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    // For values placed inside the popups' inline onclick JS strings: keeps letters in any
    // script, digits, spaces and ':' (hormuz.now:<id>, ship names) but never quotes,
    // backslashes or <>&, so a value can't break out of the string or the attribute.
    const idSafe = (s: any): string => String(s ?? '').replace(/[^\p{L}\p{N} _.:\-]/gu, '');
    const colorSafe = (s: any): string => /^#[0-9a-fA-F]{3,8}$/.test(String(s ?? '')) ? String(s) : '#aaa';

    // ── Flights ──
    ['fl-commercial','fl-private','fl-jets','fl-military'].forEach(layer => {
      map.on('click', layer, e => {
        if (!e.features?.length) return;
        const p = e.features[0].properties as any;
        const coords = (e.features[0].geometry as any).coordinates;
        const cs = (p.callsign||'').trim();
        popup(coords, `<div style="${pStyle}border:1px solid rgba(212,175,55,0.3);">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
            <span style="color:#D4AF37;font-size:16px;font-weight:700;letter-spacing:0.1em;">${htmlEsc(cs)}</span>
            <span style="color:#5C5A54;font-size:10px;">${htmlEsc(p.icao24||'')}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:11px;">
            <div><span style="color:#5C5A54;font-size:9px;">MODEL</span><br/><span style="color:#E8E6E0;">${htmlEsc(p.model||'—')}</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">ALT</span><br/><span style="color:#00E5FF;">${p.alt?Math.round(p.alt)+'m':'—'}</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">SPEED</span><br/><span style="color:#E8E6E0;">${p.speed_knots||'—'}kt</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">HDG</span><br/><span style="color:#E8E6E0;">${Math.round(p.heading||0)}°</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">REG</span><br/><span style="color:#E8E6E0;">${htmlEsc(p.registration||'—')}</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">POS</span><br/><span style="color:#E8E6E0;">${coords[1].toFixed(2)},${coords[0].toFixed(2)}</span></div>
          </div>
          <div style="margin-top:8px;font-size:10px;"><span style="color:#5C5A54;font-size:9px;">LAST UPDATE </span><span style="color:${Number(p.age_s) > STALE_AFTER_S ? '#FF9500' : '#E8E6E0'};">${ageLabel(p.age_s)}</span></div>
          <button onclick="window.openHorusIntel({ callsign: '${idSafe(cs)}', icao24: '${idSafe(p.icao24||'')}', model: '${idSafe(p.model||'')}', registration: '${idSafe(p.registration||'')}' })" style="width:100%;margin-top:8px;padding:6px 12px;background:rgba(212,175,55,0.15);border:1px solid rgba(212,175,55,0.5);color:#D4AF37;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:bold;letter-spacing:0.1em;border-radius:4px;cursor:pointer;">[ DEEP DIVE INTEL ]</button>
        </div>`);
      });
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
    });

    // ── TimeTravel replay entities (historical) — same select→deep-dive as live ──
    const ttPopup = (coords: any, p: any) => {
      const id = idSafe(String(p.asset_id || ''));
      const nm = idSafe(String(p.name || p.asset_id || ''));
      const isSea = String(p.kind || '') === 'vessel';
      const intel = isSea
        ? `window.openHorusIntel({ type: 'vessel', asset_id: '${id}', mmsi: '${/^\d{9}$/.test(id) ? id : ''}', name: '${nm}' })`
        : `window.openHorusIntel({ callsign: '${nm}', icao24: '${id}' })`;
      const glyph = isSea ? '🚢' : '✈';
      popup(coords, `<div style="${pStyle}border:1px solid rgba(255,202,40,0.4);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="color:#FFCA28;font-size:14px;font-weight:700;letter-spacing:0.1em;">${glyph} ${htmlEsc(String(p.name || p.asset_id || ''))}</span>
          <span style="color:#5C5A54;font-size:9px;">HISTORICAL</span>
        </div>
        <div style="font-size:10px;margin-bottom:8px;"><span style="color:#5C5A54;">TYPE</span> <span style="color:#E8E6E0;">${htmlEsc(String(p.asset_type || (isSea ? 'vessel' : 'aircraft')))}</span> · <span style="color:#E8E6E0;">${coords[1].toFixed(2)},${coords[0].toFixed(2)}</span></div>
        <button onclick="${intel}" style="width:100%;padding:6px 12px;background:rgba(255,202,40,0.15);border:1px solid rgba(255,202,40,0.5);color:#FFCA28;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:bold;letter-spacing:0.1em;border-radius:4px;cursor:pointer;">[ DEEP DIVE INTEL ]</button>
      </div>`);
    };
    ['tt-planes', 'tt-dots'].forEach(layer => {
      map.on('click', layer, e => {
        if (!e.features?.length) return;
        ttPopup((e.features[0].geometry as any).coordinates, e.features[0].properties as any);
      });
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
    });

    // ── CCTV (opens CameraViewer panel) ──
    map.on('click', 'cctv-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      // Emit the camera data so the CameraViewer opens
      onEntityClick?.({
        type: 'cctv',
        id: p.id,
        name: p.name,
        city: p.city,
        country: p.country,
        source: p.source,
        feed_url: p.feed_url,
        stream_url: p.stream_url,
        stream_type: p.stream_type,
        external_url: p.external_url,
        lat: coords[1],
        lng: coords[0],
      });
      // Also fly to the camera
      map.flyTo({ center: coords, zoom: Math.max(map.getZoom(), 13), duration: 1000 });
    });

    // ── Earthquakes (with USGS link) ──
    map.on('click', 'eq-circles', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      popup(coords, `<div style="${pStyle}border:1px solid rgba(255,149,0,0.3);">
        <div style="color:#FF9500;font-size:14px;font-weight:700;margin-bottom:4px;">M${p.magnitude} EARTHQUAKE</div>
        <div style="font-size:9px;color:#E8E6E0;margin-bottom:8px;">${htmlEsc(p.place||'Unknown location')}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;">
          <div><span style="color:#5C5A54;">DEPTH</span><br/><span style="color:#E8E6E0;">${p.depth||'—'}km</span></div>
          <div><span style="color:#5C5A54;">COORDS</span><br/><span style="color:#E8E6E0;">${coords[1].toFixed(3)}, ${coords[0].toFixed(3)}</span></div>
        </div>
      </div>`);
    });

    // ── Satellites (SatNOGS powered) ──
    map.on('click', 'sat-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      popup(coords, `<div style="${pStyle}border:1px solid rgba(212,175,55,0.3);">
        <div style="color:#D4AF37;font-size:12px;font-weight:700;letter-spacing:0.1em;margin-bottom:4px;">🛰️ ${htmlEsc(p.name)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;font-size:9px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;">MISSION</span><br/><span style="color:${colorSafe(p.color)};">${htmlEsc(p.mission||'Unknown')}</span></div>
          <div><span style="color:#5C5A54;">ALT</span><br/><span style="color:#00E5FF;">${p.alt ? p.alt+' km' : '—'}</span></div>
          <div><span style="color:#5C5A54;">POS</span><br/><span style="color:#E8E6E0;">${coords[1].toFixed(2)}°, ${coords[0].toFixed(2)}°</span></div>
        </div>
      </div>`);
    });

    // ── Fires (with NASA FIRMS link) ──
    map.on('click', 'fires-heat', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const volcano = p.type === 'volcano';
      // VIIRS confidence is l / n / h; MODIS gives a percentage.
      const conf = ({ l: 'LOW', n: 'NOMINAL', h: 'HIGH' } as Record<string, string>)[String(p.confidence).toLowerCase()]
        ?? (p.confidence ? `${p.confidence}%` : '—');
      const hhmm = String(p.time ?? '').padStart(4, '0');
      const detected = p.date ? `${p.date}${/^\d{4}$/.test(hhmm) ? ` ${hhmm.slice(0, 2)}:${hhmm.slice(2)}` : ''} UTC` : '—';
      popup(coords, `<div style="${pStyle}border:1px solid rgba(255,107,0,0.3);">
        <div style="color:#FF6B00;font-size:12px;font-weight:700;margin-bottom:4px;">${volcano ? '🌋 VOLCANO' : 'THERMAL ANOMALY'}</div>
        <div style="color:#8A877F;font-size:9px;margin-bottom:8px;max-width:240px;">${volcano
          ? htmlEsc(p.title || 'NASA EONET volcano event')
          : 'Satellite heat detection (NASA FIRMS, VIIRS). Usually a fire; can also be a gas flare, volcano or industrial heat source.'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;margin-bottom:8px;">
          ${volcano ? '' : `<div><span style="color:#5C5A54;">CONFIDENCE</span><br/><span style="color:#FF6B00;">${htmlEsc(conf)}</span></div>
          <div><span style="color:#5C5A54;">FIRE POWER</span><br/><span style="color:#FF6B00;">${p.frp != null && p.frp !== '' ? `${htmlEsc(p.frp)} MW` : '—'}</span></div>
          <div><span style="color:#5C5A54;">DETECTED</span><br/><span style="color:#E8E6E0;">${htmlEsc(detected)}</span></div>
          <div><span style="color:#5C5A54;">BRIGHTNESS</span><br/><span style="color:#E8E6E0;">${p.brightness ? `${htmlEsc(p.brightness)} K` : '—'}</span></div>`}
          <div><span style="color:#5C5A54;">COORDS</span><br/><span style="color:#E8E6E0;">${coords[1].toFixed(3)}°, ${coords[0].toFixed(3)}°</span></div>
        </div>
      </div>`);
    });

    // ── Malware Threats (Abuse.ch) ──
    map.on('click', 'malware-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const tType = (p.threat_type || 'MALWARE').toUpperCase();
      const statusColor = p.status === 'online' ? '#39FF14' : '#FF1744';
      
      popup(coords, `<div style="${pStyle}border:1px solid rgba(255,23,68,0.4);box-shadow:inset 0 0 12px rgba(255,23,68,0.1);">
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid rgba(255,23,68,0.3);padding-bottom:6px;margin-bottom:8px;">
          <div style="color:#FF1744;font-size:12px;font-weight:700;letter-spacing:0.1em;text-shadow:0 0 4px rgba(255,23,68,0.5);">[ ${htmlEsc(tType)} ]</div>
          <div style="color:#5C5A54;font-size:9px;">${htmlEsc(p.country || 'UNKNOWN')}</div>
        </div>
        <div style="color:#E8E6E0;font-size:11px;font-weight:bold;margin-bottom:10px;">${htmlEsc(p.malware || 'Unidentified Threat Payload')}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:9px;margin-bottom:12px;background:rgba(0,0,0,0.3);padding:6px;border-radius:4px;">
          <div><span style="color:#5C5A54;">TARGET IP</span><br/><span style="color:#00E5FF;font-family:monospace;">${htmlEsc(p.ip)}</span></div>
          <div><span style="color:#5C5A54;">STATUS</span><br/><span style="color:${statusColor};">${(p.status||'UNKNOWN').toUpperCase()}</span></div>
        </div>
        <button onclick="window.openHorusIntel({ type: 'ip', ip: '${idSafe(p.ip)}', threat_type: '${idSafe(p.malware || p.threat_type || '')}', status: '${idSafe(p.status || '')}' })" style="width:100%;margin-top:8px;padding:8px 12px;background:linear-gradient(90deg, rgba(255,23,68,0.1) 0%, rgba(255,23,68,0.2) 100%);border:1px solid rgba(255,23,68,0.6);color:#FF1744;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:bold;letter-spacing:0.15em;border-radius:4px;cursor:pointer;transition:all 0.2s;">DEEP DIVE ANALYTICS</button>
      </div>`);
    });


    // ── GDELT Conflicts (with source article) ──
    map.on('click', 'gdelt-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      

      popup(coords, `<div style="${pStyle}border:1px solid rgba(255,61,61,0.3);">
        <div style="color:#FF3D3D;font-size:12px;font-weight:700;margin-bottom:6px;">⚠️ CONFLICT EVENT</div>
        <div style="font-size:9px;color:#E8E6E0;margin-bottom:8px;line-height:1.4;">${htmlEsc(p.name||'Unclassified incident')}</div>
      </div>`);
    });

    // ── Global Event / Conflict Markers ──
    map.on('click', 'conflict-icons', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const color = p.severity === 'war' ? '#FF1744' : p.severity === 'high' ? '#FF9500' : '#FFD500';
      popup(coords, `<div style="${pStyle}border:1px solid ${color}40;">
        <div style="color:${color};font-size:12px;font-weight:700;margin-bottom:6px;">⚠️ ${htmlEsc(p.label || 'WARNING EVENT')}</div>
        <div style="font-size:10px;color:#E8E6E0;margin-bottom:8px;line-height:1.4;">${htmlEsc(p.description || 'Global event detected at this location.')}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;">SEVERITY</span><br/><span style="color:${color};">${(p.severity||'unknown').toUpperCase()}</span></div>
          <div><span style="color:#5C5A54;">COORDS</span><br/><span style="color:#E8E6E0;">${coords[1].toFixed(3)}°, ${coords[0].toFixed(3)}°</span></div>
        </div>
      </div>`);
    });


    // ── Generic hover for clickables ──
    ['conflict-icons','cctv-dots','eq-circles','sat-dots','fires-heat','gdelt-dots','weather-dots','infra-dots','maritime-dots','choke-dots','news-dots','sigint-news-dots','balloon-dots','rad-dots','ship-dots','malware-dots'].forEach(layer => {
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
    });

    // ── SCM Suppliers ──
    map.on('click', 'scm-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const color = p.risk_level === 'CRITICAL' ? '#FF1744' : p.risk_level === 'HIGH' ? '#FF9500' : '#00BCD4';
      const activeThreats = p.active_threats ? JSON.parse(p.active_threats) : [];
      
      let threatsHtml = '';
      if (activeThreats.length > 0) {
        threatsHtml = `<div style="margin-top:8px;padding-top:6px;border-top:1px solid ${color}40;color:${color};font-size:9px;font-weight:bold;">
          ACTIVE THREATS:<br/>${activeThreats.map((t: string) => `⚠ ${htmlEsc(t)}`).join('<br/>')}
        </div>`;
      }

      popup(coords, `<div style="${pStyle}border:1px solid ${color}40;">
        <div style="color:${color};font-size:12px;font-weight:700;margin-bottom:4px;">🏢 ${htmlEsc(p.name)}</div>
        <div style="font-size:9px;color:#aaa;margin-bottom:8px;">${htmlEsc(p.category)} | ${htmlEsc(p.city)}, ${htmlEsc(p.country)}</div>
        <div style="display:grid;grid-template-columns:1fr;gap:4px;font-size:11px;">
          <div><span style="color:#5C5A54;font-size:9px;">SCM RISK LEVEL</span><br/><span style="color:${color};font-weight:bold;">${p.risk_level}</span></div>
        </div>
        ${threatsHtml}
      </div>`);
    });

    // ── Balloons / Sondes ──
    map.on('click', 'balloon-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      popup(coords, `<div style="${pStyle}border:1px solid ${p.color}40;">
        <div style="color:${p.color};font-size:12px;font-weight:700;letter-spacing:0.1em;margin-bottom:4px;">🎈 ${p.callsign}</div>
        <div style="font-size:9px;color:#aaa;margin-bottom:8px;">${p.type.toUpperCase()} / STATUS: ${p.status.toUpperCase()}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;">
          <div><span style="color:#5C5A54;">ALTITUDE</span><br/><span style="color:#E8E6E0;">${p.altitude} m</span></div>
          <div><span style="color:#5C5A54;">SPEED</span><br/><span style="color:#E8E6E0;">${Math.round(p.speed)} km/h</span></div>
          <div><span style="color:#5C5A54;">VERT RATE</span><br/><span style="color:${p.verticalRate > 0 ? '#00E676' : '#FF3D3D'};">${p.verticalRate.toFixed(1)} m/s</span></div>
          <div><span style="color:#5C5A54;">TEMP</span><br/><span style="color:#E8E6E0;">${p.temperature}°C</span></div>
        </div>
      </div>`);
    });

    // ── Radiation ──
    map.on('click', 'rad-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const color = p.status === 'DANGER' ? '#FF1744' : p.status === 'WARNING' ? '#FF9500' : '#AB47BC';
      popup(coords, `<div style="${pStyle}border:1px solid ${color}40;">
        <div style="color:${color};font-size:12px;font-weight:700;margin-bottom:4px;">☢️ ${p.name}</div>
        <div style="font-size:9px;color:#aaa;margin-bottom:8px;">${p.city}, ${p.country}</div>
        <div style="display:grid;grid-template-columns:1fr;gap:4px;font-size:11px;">
          <div><span style="color:#5C5A54;font-size:9px;">READING</span><br/><span style="color:${color};font-weight:bold;">${p.reading} nSv/h</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">STATUS</span><br/><span style="color:${color};">${p.status}</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">NETWORK</span><br/><span style="color:#E8E6E0;">${p.network}</span></div>
        </div>
      </div>`);
    });

    // ── Maritime Ships ──
    map.on('click', 'ship-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const color = p.type === 'military' ? '#FF1744' : p.type === 'tanker' ? '#FF9500' : '#00E5FF';
      const icon = p.type === 'military' ? '⚔️' : p.type === 'tanker' ? '🛢️' : '🚢';
      
      popup(coords, `<div style="${pStyle}border:1px solid ${color}60;box-shadow:inset 0 0 12px ${color}15;">
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid ${color}40;padding-bottom:6px;margin-bottom:8px;">
          <div style="color:${color};font-size:12px;font-weight:700;letter-spacing:0.1em;">${icon} [ ${(p.type||'VESSEL').toUpperCase()} ]</div>
          <div style="color:#5C5A54;font-size:9px;">FLAG: ${p.flag||'UNK'}</div>
        </div>
        <div style="color:#E8E6E0;font-size:11px;font-weight:bold;margin-bottom:10px;">${p.name || 'UNIDENTIFIED VESSEL'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:9px;margin-bottom:8px;background:rgba(0,0,0,0.3);padding:6px;border-radius:4px;">
          <div><span style="color:#5C5A54;">SPEED</span><br/><span style="color:${color};font-family:monospace;">${Number(p.speed).toFixed(1)} kn</span></div>
          <div><span style="color:#5C5A54;">HEADING</span><br/><span style="color:${color};font-family:monospace;">${Number(p.heading).toFixed(0)}°</span></div>
          <div><span style="color:#5C5A54;">LATITUDE</span><br/><span style="color:#E8E6E0;font-family:monospace;">${coords[1].toFixed(4)}°</span></div>
          <div><span style="color:#5C5A54;">LONGITUDE</span><br/><span style="color:#E8E6E0;font-family:monospace;">${coords[0].toFixed(4)}°</span></div>
        </div>
        <div style="margin-bottom:4px;"><span style="color:#5C5A54;font-size:9px;">LAST UPDATE: </span><span style="color:${Number(p.age_s) > STALE_AFTER_S ? '#FF9500' : '#E8E6E0'};font-size:9px;">${ageLabel(p.age_s)}</span></div>
        <div><span style="color:#5C5A54;font-size:9px;">DESTINATION: </span><span style="color:#E8E6E0;font-size:9px;">${p.destination || 'UNKNOWN'}</span></div>
        ${p.sources ? `<div style="margin-top:4px;"><span style="color:#5C5A54;font-size:9px;">SOURCES: </span><span style="color:#E8E6E0;font-size:9px;">${String(p.sources).split(',').map(idSafe).join(' · ')}</span></div>` : ''}
        ${String(p.sources || '').split(',').includes('hormuz.now') ? `<div style="font-size:8px;color:#5C5A54;margin-top:2px;">Data: <a href="https://hormuz.now" target="_blank" rel="noopener noreferrer" style="color:#8A8780;">hormuz.now</a> (CC BY 4.0)</div>` : ''}
        <button onclick="window.openHorusIntel({ type: 'vessel', asset_id: '${idSafe(String(p.id||''))}', mmsi: '${idSafe(String(p.mmsi||''))}', imo: '${idSafe(String(p.imo||''))}', name: '${idSafe(p.name||'')}', flag: '${idSafe(p.flag||'')}', speed: '${idSafe(String(p.speed??''))}', destination: '${idSafe(p.destination||'')}' })" style="width:100%;margin-top:10px;padding:6px 12px;background:${color}26;border:1px solid ${color}80;color:${color};font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:bold;letter-spacing:0.1em;border-radius:4px;cursor:pointer;">[ DEEP DIVE INTEL ]</button>
      </div>`);
    });

    // ── Weather Events (NASA EONET) ──
    map.on('click', 'weather-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const iconEmoji = p.icon === 'cyclone' ? '🌀' : p.icon === 'volcano' ? '🌋' : '⚡';
      popup(coords, `<div style="${pStyle}border:1px solid rgba(224,64,251,0.3);">
        <div style="color:#E040FB;font-size:14px;font-weight:700;margin-bottom:6px;">${iconEmoji} ${p.type || 'Weather Event'}</div>
        <div style="font-size:10px;color:#E8E6E0;margin-bottom:8px;line-height:1.4;">${p.title || 'Unknown event'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;">SEVERITY</span><br/><span style="color:${p.severity === 'high' ? '#FF1744' : '#FFD700'};">${(p.severity||'low').toUpperCase()}</span></div>
          <div><span style="color:#5C5A54;">COORDS</span><br/><span style="color:#E8E6E0;">${coords[1].toFixed(3)}°, ${coords[0].toFixed(3)}°</span></div>
        </div>
      </div>`);
    });

    // ── Nuclear Infrastructure ──
    map.on('click', 'infra-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const statusColor = p.status.includes('SEISMIC RISK') ? '#FF9500' : p.status === 'Active Conflict Zone' ? '#FF1744' : p.status === 'Operational' ? '#76FF03' : '#757575';
      popup(coords, `<div style="${pStyle}border:1px solid rgba(118,255,3,0.3);">
        <div style="color:#76FF03;font-size:14px;font-weight:700;margin-bottom:4px;">☢️ ${p.name || 'Nuclear Facility'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:9px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;">STATUS</span><br/><span style="color:${statusColor};">${p.status || '—'}</span></div>
          <div><span style="color:#5C5A54;">CITY</span><br/><span style="color:#E8E6E0;">${p.city || '—'}, ${p.country || ''}</span></div>
          <div><span style="color:#5C5A54;">REACTORS</span><br/><span style="color:#76FF03;">${p.reactors || '—'}</span></div>
          <div><span style="color:#5C5A54;">CAPACITY</span><br/><span style="color:#E8E6E0;">${p.capacityMW ? p.capacityMW.toLocaleString() + ' MW' : '—'}</span></div>
          <div><span style="color:#5C5A54;">OWNER</span><br/><span style="color:#E8E6E0;">${p.owner || '—'}</span></div>
          <div><span style="color:#5C5A54;">COORDS</span><br/><span style="color:#E8E6E0;">${coords[1].toFixed(3)}°, ${coords[0].toFixed(3)}°</span></div>
        </div>
      </div>`);
    });

    // ── Maritime Ports & Naval Bases ──
    map.on('click', 'maritime-dots', e => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      const coords = (e.features![0].geometry as any).coordinates;
      const typeColor = p.type === 'naval' ? '#FF3D3D' : p.type === 'energy' ? '#FF9500' : '#00BCD4';
      const typeLabel = p.type === 'naval' ? 'NAVAL BASE' : p.type === 'energy' ? 'ENERGY PORT' : 'CONTAINER PORT';
      
      const congestionHtml = p.congestion ? `
        <div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;">
            <div><span style="color:#5C5A54;font-size:9px;">CONGESTION</span><br/><span style="color:${p.congestion === 'SEVERE' ? '#FF1744' : p.congestion === 'CONGESTED' ? '#FF9500' : '#00E676'};font-weight:bold;font-size:10px;">${p.congestion}</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">EST. DWELL TIME</span><br/><span style="color:#E8E6E0;font-weight:bold;font-size:10px;">${p.dwell_time || 'Unknown'}</span></div>
          </div>
        </div>` : '';

      popup(coords, `<div style="${pStyle}border:1px solid ${typeColor}40;">
        <div style="color:${typeColor};font-weight:bold;font-size:11px;margin-bottom:4px;">${p.name}</div>
        <div style="color:#999;font-size:9px;margin-bottom:6px;">${typeLabel} — ${p.country}</div>
        ${p.volume ? `<div style="font-size:9px;color:#aaa;">Volume: <span style="color:${typeColor};font-weight:bold;">${p.volume}</span></div>` : ''}
        ${p.fleet ? `<div style="font-size:9px;color:#aaa;">Fleet: <span style="color:${typeColor};font-weight:bold;">${p.fleet}</span></div>` : ''}
        ${p.rank ? `<div style="font-size:9px;color:#aaa;">Global Rank: <span style="color:${typeColor};font-weight:bold;">#${p.rank}</span></div>` : ''}
        ${congestionHtml}
      </div>`);
    });

    // ── Maritime Chokepoints ──
    map.on('click', 'choke-dots', e => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      const coords = (e.features![0].geometry as any).coordinates;
      const riskCol = p.risk === 'CRITICAL' ? '#FF1744' : p.risk === 'HIGH' ? '#FF9500' : p.risk === 'ELEVATED' ? '#FFD700' : '#00E676';
      popup(coords, `<div style="${pStyle}border:1px solid ${riskCol}40;">
        <div style="color:#FF9500;font-weight:bold;font-size:11px;margin-bottom:4px;">${p.name}</div>
        <div style="font-size:9px;color:#aaa;">Traffic: <span style="color:#fff;">${p.traffic}</span></div>
        <div style="font-size:9px;color:#aaa;">Risk: <span style="color:${riskCol};font-weight:bold;">${p.risk}</span></div>
      </div>`);
    });

    // ── Live News (opens feed viewer) ──
    map.on('click', 'news-dots', e => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      onEntityClick?.({
        type: 'live_news',
        name: p.name,
        city: p.city,
        country: p.country,
        url: p.url,
        category: p.category,
        embed_allowed: p.embed_allowed !== false && p.embed_allowed !== 'false',
      });
    });

    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Day/Night
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const update = () => {
      const src = map.getSource('day-night') as any;
      if (!src) return;
      if (!activeLayers.day_night) { src.setData(EMPTY_FC); return; }
      src.setData({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [computeSolarTerminator()] }, properties: {} }] });
    };
    update();
    const iv = setInterval(update, 300000); // 5 min (was 1 min — shadow barely moves)
    return () => clearInterval(iv);
  }, [mapReady, activeLayers.day_night]);

  // Helper to set GeoJSON
  const setGeo = useCallback((source: string, features: any[]) => {
    const src = mapRef.current?.getSource(source) as any;
    if (src) src.setData({ type: 'FeatureCollection', features });
  }, []);

  const setVis = useCallback((ids: string[], visible: boolean) => {
    const map = mapRef.current;
    if (!map) return;
    ids.forEach(id => { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none'); });
  }, []);

  // Flight data → GeoJSON (GPU rendered)
  useEffect(() => {
    if (!mapReady) return;
    const toFeatures = (arr: any[], decimate: number = 1) => {
      let filtered = arr || [];
      if (decimate > 1) {
        filtered = filtered.filter((_, i) => i % decimate === 0);
      }
      return filtered.map((f: any) => ({
        type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [f.lng, f.lat] },
        properties: { callsign: f.callsign, heading: f.heading || 0, alt: f.alt, model: f.model, speed_knots: f.speed_knots, registration: f.registration, icao24: f.icao24, airline_code: f.airline_code || '', has_airline: !!(f.airline_code && String(f.airline_code).trim().length >= 2), age_s: ageSeconds(f) },
      }));
    };
    setGeo('flights', activeLayers.flights ? toFeatures(data.commercial_flights, 10) : []);
    setGeo('private-fl', activeLayers.private ? toFeatures(data.private_flights, 2) : []);
    setGeo('jets', activeLayers.jets ? toFeatures(data.private_jets, 2) : []);
    setGeo('military', activeLayers.military ? toFeatures(data.military_flights) : []);
  }, [mapReady, data.commercial_flights, data.private_flights, data.private_jets, data.military_flights, activeLayers.flights, activeLayers.private, activeLayers.jets, activeLayers.military]);


  // ── DECOUPLED LAYER RENDERERS (Performance Optimized) ──

  useEffect(() => {
    if (!mapReady) return;
    setGeo('earthquakes', activeLayers.earthquakes && data.earthquakes ? data.earthquakes.map((eq: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [eq.lng, eq.lat] }, properties: { magnitude: eq.magnitude, place: eq.place } })) : []);
  }, [mapReady, data.earthquakes, activeLayers.earthquakes, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    const sats = data.satellites || [];
    const al = activeLayers as any;
    
    // If 'All Satellites' is on, show everything
    if (al.satellites) {
      setGeo('satellites', sats.map((s: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lng, s.lat] }, properties: { name: s.name, color: s.color, mission: s.mission, alt: s.alt, noradId: s.noradId, category: s.category } })));
      return;
    }
    
    // Otherwise filter by enabled sub-layers
    const enabledCategories: string[] = [];
    if (al.sat_comms) enabledCategories.push('comms');
    if (al.sat_military) enabledCategories.push('military');
    if (al.sat_navigation) enabledCategories.push('navigation');
    if (al.sat_earth) enabledCategories.push('earth_obs');
    if (al.sat_science) enabledCategories.push('science');
    
    if (enabledCategories.length === 0) {
      setGeo('satellites', []);
      return;
    }
    
    const filtered = sats.filter((s: any) => enabledCategories.includes(s.category));
    setGeo('satellites', filtered.map((s: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lng, s.lat] }, properties: { name: s.name, color: s.color, mission: s.mission, alt: s.alt, noradId: s.noradId, category: s.category } })));
  }, [mapReady, data.satellites, activeLayers.satellites, (activeLayers as any).sat_comms, (activeLayers as any).sat_military, (activeLayers as any).sat_navigation, (activeLayers as any).sat_earth, (activeLayers as any).sat_science, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('gdelt', activeLayers.global_incidents && data.gdelt ? data.gdelt.map((e: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [e.lng, e.lat] }, properties: { name: e.name } })) : []);
  }, [mapReady, data.gdelt, activeLayers.global_incidents, setGeo]);

  // Malware Threats
  useEffect(() => {
    if (!mapReady) return;
    setGeo('malware-nodes', activeLayers.malware && data.malware_threats ? data.malware_threats.map((t: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [t.lng, t.lat] }, properties: { ip: t.ip, malware: t.malware, status: t.status, threat_type: t.threat_type, country: t.country } })) : []);
  }, [mapReady, data.malware_threats, activeLayers.malware, setGeo]);

  // Network Mesh Generation (Nearest Neighbor Lattice)
  useEffect(() => {
    if (!mapReady) return;
    const meshLinks: any[] = [];
    
    // Generate Malware Botnet Mesh
    if (activeLayers.malware && data.malware_threats && data.malware_threats.length > 1) {
      const nodes = data.malware_threats;
      for (let i = 0; i < nodes.length; i++) {
        // Connect each to next 2 for a global web
        for (let j = 1; j <= 2; j++) {
          const target = nodes[(i + j) % nodes.length];
          meshLinks.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: [[nodes[i].lng, nodes[i].lat], [target.lng, target.lat]] },
            properties: { threat_type: 'malware' }
          });
        }
      }
    }
    setGeo('network-mesh', meshLinks);
  }, [mapReady, activeLayers.malware, data.malware_threats, setGeo]);


  useEffect(() => {
    if (!mapReady) return;
    setGeo('gps-jamming', activeLayers.gps_jamming && data.gps_jamming ? data.gps_jamming.map((z: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [z.lng, z.lat] }, properties: { severity: z.severity } })) : []);
  }, [mapReady, data.gps_jamming, activeLayers.gps_jamming, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('cctv', activeLayers.cctv && data.cameras ? data.cameras.map((c: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [c.lng, c.lat] }, properties: { id: c.id, name: c.name, city: c.city, country: c.country, source: c.source, feed_url: c.feed_url, stream_url: c.stream_url, stream_type: c.stream_type, external_url: c.external_url } })) : []);
  }, [mapReady, data.cameras, activeLayers.cctv, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('fires', activeLayers.fires && data.fires ? data.fires.map((f: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [f.lng, f.lat] }, properties: { brightness: f.brightness, confidence: f.confidence, frp: f.frp, date: f.date, time: f.time, type: f.type, title: f.title } })) : []);
  }, [mapReady, data.fires, activeLayers.fires, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('weather', activeLayers.weather && data.weather_events ? data.weather_events.map((w: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [w.lng, w.lat] }, properties: { title: w.title, type: w.type, icon: w.icon, severity: w.severity, source: w.source, id: w.id } })) : []);
  }, [mapReady, data.weather_events, activeLayers.weather, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('infrastructure', activeLayers.infrastructure && data.infrastructure ? data.infrastructure.map((i: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [i.lng, i.lat] }, properties: { name: i.name, city: i.city, country: i.country, status: i.status, reactors: i.reactors, capacityMW: i.capacityMW, owner: i.owner } })) : []);
  }, [mapReady, data.infrastructure, activeLayers.infrastructure, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('maritime', activeLayers.maritime && data.maritime_ports ? data.maritime_ports.map((p: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [p.lng, p.lat] }, properties: { name: p.name, country: p.country, type: p.type, volume: p.volume, fleet: p.fleet, rank: p.rank } })) : []);
    setGeo('maritime-choke', activeLayers.maritime && data.maritime_chokepoints ? data.maritime_chokepoints.map((c: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [c.lng, c.lat] }, properties: { name: c.name, traffic: c.traffic, risk: c.risk } })) : []);
    setGeo('maritime-ships', activeLayers.vessels && data.maritime_ships ? data.maritime_ships.map((s: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lng, s.lat] }, properties: { id: s.id ?? s.mmsi, mmsi: s.mmsi, imo: s.imo, has_imo: !!s.imo, name: s.name || s.mmsi?.toString(), type: s.type || 'cargo', speed: s.speed, heading: s.heading, destination: s.destination, flag: s.flag, age_s: ageSeconds(s), sources: Object.keys(s.sources || {}).join(',') } })) : []);
  }, [mapReady, data.maritime_ports, data.maritime_chokepoints, data.maritime_ships, activeLayers.maritime, activeLayers.vessels, setGeo]);

  // ── TimeTravel replay: paint the current frame + hide live moving layers ──
  useEffect(() => {
    if (!mapReady) return;
    const frame = timeTravelActive && timeTravelFrame ? timeTravelFrame : [];
    setGeo('timetravel', frame.map((e) => {
      const at = String(e.asset_type || '').toUpperCase();
      const domain = at.includes('VESSEL') || at.includes('SHIP') ? 'SEA'
        : (at.includes('FLIGHT') || at.includes('AIR') || at.includes('COMMERCIAL') || at.includes('MILITARY') || at.includes('JET') || at.includes('PRIVATE')) ? 'AIR'
        : 'OTHER';
      const kind = domain === 'SEA' ? 'vessel' : domain === 'AIR' ? 'aircraft' : 'other';
      return { type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [e.lng, e.lat] }, properties: { domain, kind, asset_id: e.asset_id, asset_type: e.asset_type, name: e.name || '', label: e.name || e.asset_id } };
    }));
    // While replaying, suppress the live moving layers so the historical picture is unambiguous;
    // when TimeTravel is off, restore them from activeLayers.
    setVis(['fl-commercial'], !timeTravelActive && !!activeLayers.flights);
    setVis(['fl-private'], !timeTravelActive && !!activeLayers.private);
    setVis(['fl-jets'], !timeTravelActive && !!activeLayers.jets);
    setVis(['fl-military'], !timeTravelActive && !!activeLayers.military);
    setVis(['ship-dots','ship-label'], !timeTravelActive && !!activeLayers.vessels);
  }, [mapReady, timeTravelActive, timeTravelFrame, activeLayers.flights, activeLayers.private, activeLayers.jets, activeLayers.military, activeLayers.vessels, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('balloons', activeLayers.balloons && data.balloons ? data.balloons.map((b: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [b.lng, b.lat] }, properties: { callsign: b.callsign, type: b.type, status: b.status, altitude: b.altitude, speed: b.speed, verticalRate: b.verticalRate, temperature: b.temperature, color: b.color } })) : []);
  }, [mapReady, data.balloons, activeLayers.balloons, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('radiation', activeLayers.radiation && data.radiation ? data.radiation.map((r: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.lng, r.lat] }, properties: { name: r.name, city: r.city, country: r.country, reading: r.reading, status: r.status, network: r.network } })) : []);
  }, [mapReady, data.radiation, activeLayers.radiation, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('live-news', activeLayers.live_news && data.live_feeds ? data.live_feeds.map((f: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [f.lng, f.lat] }, properties: { name: f.name, city: f.city, country: f.country, url: f.url, category: f.category, embed_allowed: f.embed_allowed !== false } })) : []);
  }, [mapReady, data.live_feeds, activeLayers.live_news, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    const items = data.news || [];
    setGeo('sigint-news', activeLayers.news_intel && items.length > 0
      ? items.filter((n: any) => n.coords?.length === 2).map((n: any) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [n.coords[1], n.coords[0]] },
          properties: { title: n.title, source: n.source, risk_score: n.risk_score, link: n.link }
        }))
      : []);
  }, [mapReady, data.news, activeLayers.news_intel, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    // 🔴 CONFLICT ZONES - center-point warning markers 🔴
    const CONFLICT_ZONES = [
      { label: 'UKRAINE WAR', severity: 'war', lat: 48.5, lng: 31.2, description: 'Live reporting: Ongoing Russian invasion of Ukraine and active frontlines.', sourceUrl: 'https://liveuamap.com/' },
      { label: 'GAZA CONFLICT', severity: 'war', lat: 31.35, lng: 34.35, description: 'Live reporting: Active military operations and humanitarian crisis in Gaza.', sourceUrl: 'https://israelpalestine.liveuamap.com/' },
      { label: 'LEBANON BORDER', severity: 'high', lat: 33.377, lng: 35.483, description: 'Live reporting: An airstrike targeted the city of Nabatieh.', sourceUrl: 'https://lebanon.liveuamap.com/en/2026/6-june-11-an-airstrike-targeted-the-city-of-nabatieh' },
      { label: 'SUDAN CIVIL WAR', severity: 'war', lat: 15.0, lng: 30.0, description: 'Live reporting: Armed conflict between SAF and RSF factions across Sudan.', sourceUrl: 'https://sudan.liveuamap.com/' },
      { label: 'MYANMAR CONFLICT', severity: 'war', lat: 19.5, lng: 96.5, description: 'Live reporting: Internal conflict and military junta opposition operations.', sourceUrl: 'https://myanmar.liveuamap.com/' },
      { label: 'DRC EASTERN CONFLICT', severity: 'war', lat: -1.0, lng: 28.5, description: 'M23 rebel offensive and regional instability.' },
      { label: 'YEMEN WAR', severity: 'war', lat: 15.5, lng: 48.0, description: 'Houthi militant operations and Red Sea maritime threats.', sourceUrl: 'https://yemen.liveuamap.com/' },
      { label: 'SYRIA', severity: 'high', lat: 35.0, lng: 38.5, description: 'Live reporting: Ongoing civil war and localized insurgencies.', sourceUrl: 'https://syria.liveuamap.com/' },
      { label: 'TAIWAN STRAIT', severity: 'elevated', lat: 24.0, lng: 119.5, description: 'Elevated military drills and regional tension.' },
      { label: 'KOREAN DMZ', severity: 'elevated', lat: 38.3, lng: 127.0, description: 'Ongoing cross-border tension and military posturing.' },
      { label: 'SAHEL INSTABILITY', severity: 'high', lat: 14.0, lng: 5.0, description: 'Insurgencies and military coups across the Sahel region.' },
      { label: 'SOMALIA', severity: 'high', lat: 5.0, lng: 46.0, description: 'Al-Shabaab insurgency and counter-terrorism operations.' },
      { label: 'RED SEA THREAT', severity: 'high', lat: 16.0, lng: 40.0, description: 'Houthi anti-ship missile and drone attacks on maritime traffic.', sourceUrl: 'https://yemen.liveuamap.com/' },
    ];
    const conflictFeatures = CONFLICT_ZONES.map(z => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [z.lng, z.lat] },
      properties: { label: z.label, severity: z.severity, description: z.description, sourceUrl: z.sourceUrl },
    }));
    setGeo('conflict-zones', conflictFeatures);
  }, [mapReady, setGeo]);


  // Visibility
  useEffect(() => {
    if (!mapReady) return;
    setVis(['eq-circles','eq-label'], activeLayers.earthquakes);
    const anySat = activeLayers.satellites || (activeLayers as any).sat_comms || (activeLayers as any).sat_military || (activeLayers as any).sat_navigation || (activeLayers as any).sat_earth || (activeLayers as any).sat_science;
    setVis(['sat-glow','sat-dots'], anySat);
    setVis(['gdelt-dots'], activeLayers.global_incidents);

    setVis(['malware-glow','malware-dots','malware-label'], activeLayers.malware);
    setVis(['network-mesh-atmo', 'network-mesh-glow', 'network-mesh-core'], activeLayers.internet_outages || activeLayers.malware);
    setVis(['jam-fill','jam-label'], activeLayers.gps_jamming);
    setVis(['day-night-fill'], activeLayers.day_night);
    setVis(['fl-commercial'], activeLayers.flights);
    setVis(['fl-private'], activeLayers.private);
    setVis(['fl-jets'], activeLayers.jets);
    setVis(['fl-military'], activeLayers.military);
    setVis(['cctv-glow','cctv-dots','cctv-label'], activeLayers.cctv);
    setVis(['fires-heat'], activeLayers.fires);
    setVis(['weather-glow','weather-dots','weather-label'], activeLayers.weather);
    setVis(['infra-glow','infra-dots','infra-label'], activeLayers.infrastructure);
    setVis(['maritime-glow','maritime-dots','maritime-label'], activeLayers.maritime);
    setVis(['choke-glow','choke-dots','choke-label'], activeLayers.maritime);
    setVis(['ship-dots','ship-label'], activeLayers.vessels);
    setVis(['news-glow','news-dots','news-label'], activeLayers.live_news);
    setVis(['sigint-news-glow','sigint-news-dots','sigint-news-label'], activeLayers.news_intel);
    setVis(['conflict-icons'], activeLayers.conflict_zones !== false);

    setVis(['balloon-dots','balloon-label'], activeLayers.balloons);
    setVis(['rad-glow','rad-dots','rad-label'], activeLayers.radiation);
  }, [mapReady, activeLayers, setVis]);

  // Fly-to
  useEffect(() => {
    if (!mapReady || !mapRef.current || !flyToLocation) return;
    mapRef.current.flyTo({ center: [flyToLocation.lng, flyToLocation.lat], zoom: flyToLocation.zoom || 8, duration: 2000 });
  }, [mapReady, flyToLocation]);

  // Dynamic projection switching (lightweight — no terrain DEM)
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    try {
      (map as any).setProjection({ type: projection });
      if (projection === 'globe') {
        map.easeTo({ pitch: 20, duration: 1200 });
        try {
          (map as any).setSky({
            'sky-color': '#04040A',
            'sky-horizon-blend': 0.5,
            'horizon-color': '#0a0a1a',
            'horizon-fog-blend': 0.3,
            'fog-color': '#04040A',
            'fog-ground-blend': 0.9,
          });
        } catch (e) { console.warn('[HORUS] Suppressed error:', e instanceof Error ? e.message : e); }
      } else {
        map.easeTo({ pitch: 0, duration: 800 });
      }
    } catch (e) {
      console.warn('Projection switch failed:', e);
    }
  }, [mapReady, projection]);

  // 3D Terrain & Buildings layer
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const enabled = activeLayers.terrain_3d;

    try {
      if (enabled) {
        // ── 3D BUILDINGS SOURCE (OpenFreeMap CDN — no API key, globally cached) ──
        if (!map.getSource('horus-buildings')) {
          map.addSource('horus-buildings', {
            type: 'vector',
            url: 'https://tiles.openfreemap.org/planet',
          });
        }

        // ── 3D BUILDING EXTRUSION LAYER ──
        if (!map.getLayer('horus-3d-buildings')) {
          map.addLayer({
            id: 'horus-3d-buildings',
            source: 'horus-buildings',
            'source-layer': 'building',
            type: 'fill-extrusion',
            minzoom: 14.5,
            paint: {
              'fill-extrusion-color': [
                'interpolate', ['linear'], ['get', 'render_height'],
                0, '#1a1a2e',
                20, '#16213e',
                50, '#0f3460',
                120, '#533483',
                300, '#e94560',
              ],
              'fill-extrusion-height': [
                'interpolate', ['linear'], ['zoom'],
                14.5, 0,
                15.5, ['get', 'render_height']
              ],
              'fill-extrusion-base': [
                'interpolate', ['linear'], ['zoom'],
                14.5, 0,
                15.5, ['get', 'render_min_height']
              ],
              'fill-extrusion-opacity': [
                'interpolate', ['linear'], ['zoom'],
                14.5, 0,
                15, 0.7,
              ],
            },
          });
        }

        // Pitch the camera to reveal the 3D skyline
        if (map.getPitch() < 40) {
          map.easeTo({ pitch: 50, duration: 1200 });
        }

      } else {
        // ── DISABLE 3D ──
        if (map.getLayer('horus-3d-buildings')) map.removeLayer('horus-3d-buildings');
      }
    } catch (e) {
      console.warn('[HORUS] 3D terrain toggle error:', e);
    }
  }, [mapReady, activeLayers.terrain_3d]);

  // Satellite / Dark style switching
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    if (mapStyle === prevStyleRef.current) return;
    prevStyleRef.current = mapStyle;
    const map = mapRef.current;

    try {
      if (mapStyle !== 'dark') {
        // Add satellite raster tiles
        if (!map.getSource('satellite-tiles')) {
          map.addSource('satellite-tiles', {
            type: 'raster',
            tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
            tileSize: 256,
            maxzoom: 18,
          });
          map.addLayer({ id: 'satellite-layer', type: 'raster', source: 'satellite-tiles', paint: { 'raster-opacity': 0.85 } }, 'day-night-fill');
        } else {
          map.setLayoutProperty('satellite-layer', 'visibility', 'visible');
        }
      } else {
        if (map.getLayer('satellite-layer')) {
          map.setLayoutProperty('satellite-layer', 'visibility', 'none');
        }
      }
    } catch (e) {
      console.warn('Style switch failed:', e);
    }
  }, [mapReady, mapStyle]);

  return <div ref={containerRef} className="absolute inset-0 w-full h-full" />;
}

export default memo(HorusMap);
