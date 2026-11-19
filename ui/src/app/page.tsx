'use client';

import { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { MIGRATED_FEEDS } from '@/lib/connectionMode';
import { motion, AnimatePresence } from 'framer-motion';
import { Layers, Newspaper, Search, X, Globe, MapPinned, Satellite, Moon, ExternalLink, AlertTriangle, Activity, Database, Wifi, Play, Network, Crosshair } from 'lucide-react';
import IntelFeed from '@/components/IntelFeed';
import ScmPanel from '@/components/ScmPanel';
import SearchBar from '@/components/SearchBar';
import ScaleBar from '@/components/ScaleBar';
import ErrorBoundary from '@/components/ErrorBoundary';
import SharePanel from '@/components/SharePanel';
import ViewPresets from '@/components/ViewPresets';
import KeyboardShortcuts from '@/components/KeyboardShortcuts';
import LiveAlerts from '@/components/LiveAlerts';

const HorusMap = dynamic(() => import('@/components/HorusMap'), { ssr: false });
const LayerPanel = dynamic(() => import('@/components/LayerPanel'));
const CameraViewer = dynamic(() => import('@/components/CameraViewer'));
const EntityGraphPanel = dynamic(() => import('@/components/EntityGraphPanel'));
const RecorderControl = dynamic(() => import('@/components/RecorderControl'));
const SecuredConnection = dynamic(() => import('@/components/SecuredConnection'));
const TimeTravelBar = dynamic(() => import('@/components/TimeTravelBar'), { ssr: false });

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      // Mobile if narrow, OR landscape phone (short height + moderate width)
      setIsMobile(w < 768 || (h < 500 && w < 1024));
    };
    check();
    window.addEventListener('resize', check);
    window.addEventListener('orientationchange', check);
    return () => {
      window.removeEventListener('resize', check);
      window.removeEventListener('orientationchange', check);
    };
  }, []);
  return isMobile;
}
const UptimeClock = () => {
  const [uptime, setUptime] = useState('00:00:00');
  const startTime = useRef(0);
  if (startTime.current === 0) startTime.current = Date.now();
  useEffect(() => {
    const iv = setInterval(() => {
      const e = Math.floor((Date.now() - startTime.current) / 1000);
      setUptime(`${String(Math.floor(e/3600)).padStart(2,'0')}:${String(Math.floor((e%3600)/60)).padStart(2,'0')}:${String(e%60).padStart(2,'0')}`);
    }, 1000);
    return () => clearInterval(iv);
  }, []);
  return <span className="hidden lg:inline">UPTIME: <span className="text-[var(--gold-primary)]">{uptime}</span></span>;
};

/** Real entity count — no fake throughput metrics */
const ActiveEntityCount = ({ data }: { data: Record<string, unknown[]> }) => {
  const count = useMemo(() => {
    if (!data) return 0;
    return Object.values(data).reduce((sum, v) => sum + (Array.isArray(v) ? v.length : 0), 0);
  }, [data]);
  return <span className="text-[var(--alert-green)] font-bold tabular-nums">{count.toLocaleString()}</span>;
};

/** Extracts a watchable YouTube URL from embed/channel URLs */
function getYouTubeWatchUrl(url: string): string {
  if (url.includes('channel=')) return `https://www.youtube.com/channel/${url.split('channel=')[1].split('&')[0]}/live`;
  if (url.includes('/embed/')) return `https://www.youtube.com/watch?v=${url.split('/embed/')[1].split('?')[0]}`;
  return url;
}

/** Fly to the visitor's city on load (IP geolocation via /api/geo). Off in Horus. */
const FLY_TO_VISITOR_CITY = false;

export default function Dashboard() {
  const dataRef = useRef<any>({});
  const [dataVersion, setDataVersion] = useState(0);
  const data = dataRef.current;

  // SECURED CONNECTION: when secured, the UI must only consume migrated (NiFi)
  // feeds. connModeRef holds the authoritative server state; reloadKey forces the
  // data loaders to re-run when the mode flips.
  const connModeRef = useRef<{ secured: boolean; migrated: string[] }>({ secured: true, migrated: [...MIGRATED_FEEDS] });
  // Reactive mirror of connModeRef.secured so the layer loaders re-run once the
  // authoritative mode is known (a ref alone doesn't trigger the effect).
  const [securedMode, setSecuredMode] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  const [backendStatus, setBackendStatus] = useState<'connecting' | 'connected' | 'error'>('connecting');
  const [mapView, setMapView] = useState({ zoom: 2.5, latitude: 20 });
  const [flyToLocation, setFlyToLocation] = useState<{ lat: number; lng: number; zoom?: number; ts: number } | null>(null);
  const [globalStats, setGlobalStats] = useState<any>(null);
  const mouseCoordsRef = useRef<{ lat: number; lng: number } | null>(null);
  const coordsDisplayRef = useRef<HTMLDivElement>(null);
  const [locationLabel, setLocationLabel] = useState('');
  const [regionDossier, setRegionDossier] = useState<any>(null);
  const [dossierLoading, setDossierLoading] = useState(false);
  const [activeCamera, setActiveCamera] = useState<any>(null);
  const [showLayers, setShowLayers] = useState(true);
  const [showAlerts, setShowAlerts] = useState(false);
  const [showScmPanel, setShowScmPanel] = useState(true);
  const [showEntityGraph, setShowEntityGraph] = useState(false);
  const [showDesktopSearch, setShowDesktopSearch] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<'layers'|'intel'|'search'|null>(null);
  const [mapProjection, setMapProjection] = useState<'globe'|'mercator'>('globe');
  const [mapStyle, setMapStyle] = useState<'dark'|'satellite'>('dark');
  const [entityGraphTarget, setEntityGraphTarget] = useState<{ type: string; id: string; label?: string; properties?: Record<string, any> } | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [timeTravelActive, setTimeTravelActive] = useState(false);
  const [timeTravelFrame, setTimeTravelFrame] = useState<any[]>([]);

  const isMobile = useIsMobile();
  const startTime = useRef(Date.now());
  const geocodeCache = useRef<Map<string, string>>(new Map());
  const geocodeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastGeocodedPos = useRef<{ lat: number; lng: number } | null>(null);

  // ── DEFAULT: Most layers OFF — fast initial load ──
  // Fresh load: every layer/feed starts OFF so the canvas opens clean. Selections
  // are restored from the ?layers= URL param below if one is present.
  const [activeLayers, setActiveLayers] = useState({
    flights: false,
    private: false,
    jets: false,
    military: false,
    maritime: false,
    vessels: false,
    satellites: false,
    sat_comms: false,
    sat_military: false,
    sat_navigation: false,
    sat_earth: false,
    sat_science: false,
    balloons: false,
    cctv: false,
    live_news: false,
    news_intel: false,
    earthquakes: false,
    fires: false,
    weather: false,
    radiation: false,
    infrastructure: false,
    global_incidents: false,
    war_alerts: false,
    gps_jamming: false,
    day_night: false,
    cables: false,
    terrain_3d: false,
    malware: false,
  });
  const [liveFeedUrl, setLiveFeedUrl] = useState<string | null>(null);
  const [liveFeedName, setLiveFeedName] = useState('');
  const [liveFeedEmbedAllowed, setLiveFeedEmbedAllowed] = useState(true);

  // PIPELINE mode: turn off the views that load public map tiles (Esri satellite
  // imagery, OpenFreeMap 3D buildings) so the browser only talks to Horus.
  useEffect(() => {
    if (!securedMode) return;
    setMapStyle('dark');
    setActiveLayers(prev => (prev.terrain_3d ? { ...prev, terrain_3d: false } : prev));
  }, [securedMode, activeLayers.terrain_3d]);

  // On mount: restore layers and deep links from the URL (IP fly-to is disabled below)
  useEffect(() => {
    if (typeof window === 'undefined') return;

    // Restore active layers from URL if present
    const p = new URLSearchParams(window.location.search);
    const layers = p.get('layers');
    if (layers) {
      const active = layers.split(',');
      setActiveLayers(prev => {
        const next = { ...prev };
        Object.keys(next).forEach(k => { (next as any)[k] = active.includes(k); });
        return next;
      });
    }

    // Deep-link: ?lat=..&lng=..(&zoom=..) flies straight to a location on load and
    // skips the default IP geolocation so a shared link isn't overridden. `lon` is
    // accepted as an alias for `lng`.
    const qLat = parseFloat(p.get('lat') || '');
    const qLng = parseFloat(p.get('lng') || p.get('lon') || '');
    if (Number.isFinite(qLat) && Number.isFinite(qLng)) {
      const qZoom = parseFloat(p.get('zoom') || '');
      const zoom = Number.isFinite(qZoom) ? qZoom : 10;
      setFlyToLocation({ lat: qLat, lng: qLng, zoom, ts: Date.now() });
      setMapView(v => ({ ...v, zoom }));
      return;   // deep-linked to coordinates — don't run IP geolocation
    }

    // "Fly to your city" by IP geolocation. Disabled for Horus: it calls a public
    // IP-lookup service (not air-gap safe), and in Workbench the UI server sees the
    // ingress address, not the viewer's. Set FLY_TO_VISITOR_CITY to re-enable.
    if (!FLY_TO_VISITOR_CITY) return;
    const geoTimer = setTimeout(() => {
      fetch('/api/geo')
        .then(r => r.json())
        .then(geo => {
          if (geo.status === 'success' && geo.lat && geo.lon) {
            setFlyToLocation({ lat: geo.lat, lng: geo.lon, ts: Date.now() });
            setMapView(v => ({ ...v, zoom: 12 }));
          }
        })
        .catch(() => { /* silent — keep default global view */ });
    }, 3000);

    return () => clearTimeout(geoTimer);
  }, []);

  // URL state: persist active layers only (lat/lon comes from IP geolocation on each load)
  const urlTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (urlTimer.current) clearTimeout(urlTimer.current);
    urlTimer.current = setTimeout(() => {
      const active = Object.entries(activeLayers).filter(([,v]) => v).map(([k]) => k).join(',');
      const url = `${window.location.pathname}?layers=${active}`;
      window.history.replaceState(null, '', url);
    }, 1500);
  }, [activeLayers]);

  // Global Stats Fetch
  useEffect(() => {
    fetch('/api/stats')
      .then(res => res.json())
      .then(d => {
        if (d.stats) setGlobalStats(d.stats);
      })
      .catch(console.error);
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as Element)?.tagName)) return;
      if (e.key === 'f' && !e.ctrlKey) {
        if (document.fullscreenElement) document.exitFullscreen();
        else document.documentElement.requestFullscreen();
      }
      if (e.key === 'l') setShowLayers(p => !p);
      if (e.key === 'c') setShowScmPanel(p => !p);
      if (e.key === 's') { setShowDesktopSearch(p => !p); setShowAlerts(false); }
      if (e.key === 'r') setFlyToLocation({ lat: 20, lng: 0, ts: Date.now() });
      if (e.key === 'g') setMapProjection(p => p === 'globe' ? 'mercator' : 'globe');
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        setShowDesktopSearch(true); setShowAlerts(false);
      }
    };
    const fsHandler = () => setIsFullscreen(!!document.fullscreenElement);
    window.addEventListener('keydown', handler);
    document.addEventListener('fullscreenchange', fsHandler);
    return () => { window.removeEventListener('keydown', handler); document.removeEventListener('fullscreenchange', fsHandler); };
  }, []);

  // Mouse coords + reverse geocode (Zero-Render)
  const handleMouseCoords = useCallback((coords: { lat: number; lng: number }) => {
    mouseCoordsRef.current = coords;
    if (coordsDisplayRef.current) {
      coordsDisplayRef.current.innerText = `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}`;
    }
    if (geocodeTimer.current) clearTimeout(geocodeTimer.current);
    // PIPELINE mode: no reverse geocode. It calls the public Nominatim service
    // from the browser, so only coordinates are shown (air-gap safe).
    if (connModeRef.current.secured) return;
    geocodeTimer.current = setTimeout(async () => {
      if (lastGeocodedPos.current) {
        const d = Math.abs(coords.lat - lastGeocodedPos.current.lat) + Math.abs(coords.lng - lastGeocodedPos.current.lng);
        if (d < 0.5) return; // increased threshold — fewer geocode calls
      }
      const gk = `${coords.lat.toFixed(1)},${coords.lng.toFixed(1)}`; // coarser grid = more cache hits
      if (geocodeCache.current.has(gk)) { setLocationLabel(geocodeCache.current.get(gk)!); lastGeocodedPos.current = coords; return; }
      try {
        const res = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${coords.lat}&lon=${coords.lng}&format=json&zoom=10&addressdetails=1`, { headers: { 'Accept-Language': 'en' } });
        if (res.ok) {
          const d = await res.json();
          const a = d.address || {};
          const label = [a.city||a.town||a.village||a.county, a.state||a.region, a.country].filter(Boolean).join(', ') || 'Unknown';
          if (geocodeCache.current.size > 500) { const it = geocodeCache.current.keys(); for (let i=0;i<100;i++) { const k = it.next().value; if(k) geocodeCache.current.delete(k); }}
          geocodeCache.current.set(gk, label);
          setLocationLabel(label);
          lastGeocodedPos.current = coords;
        }
      } catch (e) { console.warn('[HORUS] Suppressed error:', e instanceof Error ? e.message : e); }
    }, 3000); // 3s debounce (was 1.5s)
  }, []);

  // Region dossier (right-click)
  const handleRightClick = useCallback(async (coords: { lat: number; lng: number }) => {
    setDossierLoading(true); setRegionDossier(null);
    try {
      const res = await fetch(`/api/region-dossier?lat=${coords.lat}&lng=${coords.lng}`);
      if (res.ok) setRegionDossier(await res.json());
    } catch (e) { console.warn('[HORUS] Suppressed error:', e instanceof Error ? e.message : e); } finally { setDossierLoading(false); }
  }, []);
  // Entity click handler (hoisted from JSX to comply with Rules of Hooks - Fixes #113)
  const handleEntityClick = useCallback((entity: any) => {
    if (entity?.type === 'cctv') setActiveCamera(entity);
    if (entity?.type === 'live_news' && entity.url) {
      setLiveFeedUrl(entity.url);
      setLiveFeedName(entity.name);
      setLiveFeedEmbedAllowed(entity.embed_allowed !== false);
    }
  }, []);

  // Global handler for map popups to manually open the Intel Graph
  useEffect(() => {
    (window as any).openHorusIntel = (entity: any) => {
      if (entity?.callsign || entity?.icao24) {
        setEntityGraphTarget({ type: 'aircraft', id: entity.callsign?.trim() || entity.icao24, label: entity.callsign?.trim() || entity.icao24, properties: { model: entity.model, registration: entity.registration, icao24: entity.icao24 } });
        setShowEntityGraph(true);
      } else if (entity?.type === 'vessel' || entity?.mmsi || entity?.imo) {
        setEntityGraphTarget({ type: 'vessel', id: entity.imo || entity.mmsi || entity.name, label: entity.name || entity.imo, properties: { flag: entity.flag, speed: entity.speed, destination: entity.destination, mmsi: entity.mmsi, imo: entity.imo } });
        setShowEntityGraph(true);
      } else if (entity?.type === 'ip' && entity?.ip) {
        setEntityGraphTarget({ type: 'ip', id: entity.ip, label: entity.ip, properties: { threat_type: entity.threat_type, status: entity.status } });
        setShowEntityGraph(true);
      } else if (entity?.type === 'country' && entity?.country) {
        setEntityGraphTarget({ type: 'country', id: entity.country, label: entity.country, properties: {} });
        setShowEntityGraph(true);
      }
    };
    return () => { delete (window as any).openHorusIntel; };
  }, []);

  // ── SHARED FETCH UTILITY (Fixes #107 — single definition, not 3 copies) ──
  // Returns true only if a fetch was actually performed and succeeded; false if it
  // was suppressed (secured gate / tab hidden) or errored. Callers use this to avoid
  // permanently marking a layer "loaded" when nothing was actually fetched.
  const fetchEndpoint = useCallback(async (url: string, transform?: (d: any) => any, options?: RequestInit): Promise<boolean> => {
    if (typeof document !== 'undefined' && document.hidden) return false;
    // SECURED CONNECTION: in secured mode, only fetch migrated (NiFi-backed)
    // feeds. All other public-API feeds are suppressed so the UI uses streaming
    // lakehouse data only. (Backend routes stay live so the recorder can still
    // persist every feed to the lake.)
    if (connModeRef.current.secured) {
      // Route path != feed name for maritime: the route is /api/maritime but the
      // migrated feed is named "vessels". Without this alias the vessels layer is
      // suppressed in secured mode and never paints, even though the gateway has
      // vessels. Extend this map if any future route name diverges from its feed.
      const ROUTE_TO_FEED: Record<string, string> = { maritime: 'vessels' };
      const route = url.split('?')[0].replace('/api/', '');
      const feed = ROUTE_TO_FEED[route] ?? route;
      if (!connModeRef.current.migrated.includes(feed)) return false;
    }
    try {
      // Force the browser to bypass its local disk cache for real-time data
      const res = await fetch(url, { ...options, cache: 'no-store' });
      if (res.ok) {
        const json = await res.json();
        const d = transform ? transform(json) : json;
        dataRef.current = { ...dataRef.current, ...d };
        setDataVersion(v => v + 1);
        setBackendStatus('connected');
        return true;
      }
      return false;
    } catch (e) {
      console.warn('[HORUS] Suppressed error:', e instanceof Error ? e.message : e);
      setBackendStatus('error');
      return false;
    }
  }, []);

  // ── PROGRESSIVE DATA LOADING (request-optimized) ──
  useEffect(() => {
    // Priority 1: Core feeds (always needed for panels)
    fetchEndpoint('/api/earthquakes');
    fetchEndpoint('/api/news');

    // Polling — OPTIMIZED intervals to minimize edge requests
    const intervals = [
      setInterval(() => fetchEndpoint('/api/earthquakes'), 900000),  // 15 min (was 5)
      setInterval(() => fetchEndpoint('/api/news'), 1800000),        // 30 min (was 10)
    ];
    return () => {
      intervals.forEach(clearInterval);
    };
  }, [fetchEndpoint, reloadKey]);

  // ── SECURED CONNECTION: sync mode on mount + react to toggle ──
  // On mount we read the authoritative server mode. SecuredConnection.tsx
  // dispatches 'horus-connection-mode' on toggle; on any change we clear ALL
  // feed data and force every loader to re-run under the new mode so non-migrated
  // (public-API) layers are emptied in secured mode and restored in direct mode.
  useEffect(() => {
    const apply = async (force: boolean) => {
      let changed = force;
      try {
        const r = await fetch('/api/connection-mode', { cache: 'no-store' });
        const d = await r.json();
        const next = {
          secured: !!d.secured,
          migrated: Array.isArray(d.migratedFeeds) ? d.migratedFeeds : ['earthquakes'],
        };
        if (next.secured !== connModeRef.current.secured) changed = true;
        connModeRef.current = next;
        setSecuredMode(next.secured);  // drive the reactive dep so loaders re-run
      } catch { /* keep last known mode */ }
      if (changed) {
        dataRef.current = {};
        layerFetchedRef.current.clear();
        setDataVersion(v => v + 1);
        setReloadKey(k => k + 1);
      }
    };
    const onEvent = () => apply(true);
    // Mount: only force a reload if the server mode differs from the default
    // pipeline (secured) assumption, avoiding a redundant double-fetch.
    apply(false);
    window.addEventListener('horus-connection-mode', onEvent);
    return () => window.removeEventListener('horus-connection-mode', onEvent);
  }, []);

  // ── LAYER-AWARE DATA LOADING — only fetch when layer is toggled ON ──
  const layerFetchedRef = useRef<Set<string>>(new Set());
  useEffect(() => {

    // A layer is only marked "loaded" once a fetch actually succeeds. A fetch that
    // was suppressed (connection mode not settled yet) or errored is NOT stranded —
    // it clears the flag so the next effect run (e.g. when securedMode resolves)
    // retries it. This is what makes "Secure ON → then select aviation" populate
    // without the Secure OFF/ON toggle workaround.
    const loadOnce = (key: string, run: () => Promise<boolean>) => {
      if (layerFetchedRef.current.has(key)) return;
      layerFetchedRef.current.add(key);
      run().then(ok => { if (!ok) layerFetchedRef.current.delete(key); });
    };

    // Flights
    if (activeLayers.flights || activeLayers.military || activeLayers.jets || activeLayers.private) {
      loadOnce('flights', () => fetchEndpoint('/api/flights'));
    }
    // Satellites (any satellite sub-layer triggers fetch)
    const anySatLayer = activeLayers.satellites || activeLayers.sat_comms || activeLayers.sat_military || activeLayers.sat_navigation || activeLayers.sat_earth || activeLayers.sat_science;
    if (anySatLayer && !layerFetchedRef.current.has('satellites')) {
      fetchEndpoint('/api/satellites');
      layerFetchedRef.current.add('satellites');
    }
    // Fires
    if (activeLayers.fires && !layerFetchedRef.current.has('fires')) {
      fetchEndpoint('/api/fires');
      layerFetchedRef.current.add('fires');
    }
    // CCTV
    if (activeLayers.cctv && !layerFetchedRef.current.has('cctv')) {
      fetchEndpoint('/api/cctv?region=all&v=2');
      layerFetchedRef.current.add('cctv');
    }
    // Maritime
    if (activeLayers.maritime || activeLayers.vessels) {
      loadOnce('maritime', () => fetchEndpoint('/api/maritime', d => ({ maritime_ports: d.ports, maritime_chokepoints: d.chokepoints, maritime_ships: d.ships })));
    }
    // Balloons
    if (activeLayers.balloons && !layerFetchedRef.current.has('balloons')) {
      fetchEndpoint('/api/balloons', d => ({ balloons: d.balloons }));
      layerFetchedRef.current.add('balloons');
    }
    // Radiation
    if (activeLayers.radiation && !layerFetchedRef.current.has('radiation')) {
      fetchEndpoint('/api/radiation', d => ({ radiation: d.stations }));
      layerFetchedRef.current.add('radiation');
    }
    // Live News
    if (activeLayers.live_news && !layerFetchedRef.current.has('live_news')) {
      fetchEndpoint('/api/live-news', d => ({ live_feeds: d.feeds }));
      layerFetchedRef.current.add('live_news');
    }
    // Weather
    if (activeLayers.weather && !layerFetchedRef.current.has('weather')) {
      fetchEndpoint('/api/weather', d => ({ weather_events: d.events }));
      layerFetchedRef.current.add('weather');
    }
    // Infrastructure
    if (activeLayers.infrastructure && !layerFetchedRef.current.has('infrastructure')) {
      fetchEndpoint('/api/infrastructure', d => ({ infrastructure: d.infrastructure }));
      layerFetchedRef.current.add('infrastructure');
    }
    // Global Incidents (GDELT)
    if (activeLayers.global_incidents && !layerFetchedRef.current.has('gdelt')) {
      fetchEndpoint('/api/gdelt', d => ({ gdelt: d.events }));
      layerFetchedRef.current.add('gdelt');
    }

    // Submarine Cables (local static reference asset bundled in /public/data —
    // no external egress, so it is air-gap-safe and MUST render in secured mode
    // too, unlike public-API feeds. Do NOT gate this on connModeRef.secured.)
    if (activeLayers.cables && !layerFetchedRef.current.has('cables')) {
      (async () => {
        try {
          const ts = Date.now();
      const res = await fetch(`/data/submarine-cables.json?v=${ts}`);
          if (res.ok) {
             const cablesData = await res.json();
             dataRef.current = { ...dataRef.current, submarine_cables: cablesData.features };
             setDataVersion(v => v + 1);
          }
        } catch (e) { console.warn('Cables fetch failed'); }
      })();
      layerFetchedRef.current.add('cables');
    }


    // Live Malware (abuse.ch)
    if (activeLayers.malware && !layerFetchedRef.current.has('malware')) {
      fetchEndpoint('/api/malware', d => ({ malware_threats: d.threats }));
      layerFetchedRef.current.add('malware');
    }


  }, [activeLayers, reloadKey, securedMode]);

  // ── LAYER-AWARE POLLING — only poll data for active layers ──
  useEffect(() => {
    const intervals: ReturnType<typeof setInterval>[] = [];
    if (activeLayers.flights || activeLayers.military || activeLayers.jets || activeLayers.private) {
      // 30s: also acts as the safety net if the very first fetch landed before the
      // gateway's flight feed had filled (secured mode), so aircraft appear promptly.
      intervals.push(setInterval(() => fetchEndpoint('/api/flights'), 30000));
    }

    if (activeLayers.balloons) {
      intervals.push(setInterval(() => fetchEndpoint('/api/balloons', d => ({ balloons: d.balloons })), 300000)); // 5m
    }
    if (activeLayers.radiation) {
      intervals.push(setInterval(() => fetchEndpoint('/api/radiation', d => ({ radiation: d.stations })), 300000)); // 5m
    }
    if (activeLayers.maritime || activeLayers.vessels) {
      intervals.push(setInterval(() => fetchEndpoint('/api/maritime', d => ({ maritime_ports: d.ports, maritime_chokepoints: d.chokepoints, maritime_ships: d.ships })), 10000)); // 10s
    }
    return () => intervals.forEach(clearInterval);
  }, [activeLayers, fetchEndpoint, reloadKey, securedMode]);

  // CCTV: loaded once on layer toggle via layerFetchedRef (no viewport polling)

  // Reactive layer fetch: handled by layerFetchedRef above (no duplicate)

  const totalFlights = useMemo(() => (
    (data.commercial_flights?.length||0)+(data.private_flights?.length||0)+(data.private_jets?.length||0)+(data.military_flights?.length||0)
  ), [data.commercial_flights, data.private_flights, data.private_jets, data.military_flights]);


  return (
    <main className="fixed inset-0 w-full h-full bg-[var(--bg-void)] overflow-hidden">




      {/* ── MAP ── */}
      <ErrorBoundary name="Map">
        <HorusMap 
          allowPublicTiles={!securedMode}
          data={data} 
          activeLayers={activeLayers} 
          projection={mapProjection} 
          mapStyle={mapStyle === 'satellite' ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}' : 'dark'} 
          onEntityClick={handleEntityClick} 
          onMouseCoords={handleMouseCoords} 
          onRightClick={handleRightClick} 
          onViewStateChange={setMapView} 
          flyToLocation={flyToLocation}
          demoMode={demoMode}
          timeTravelActive={timeTravelActive}
          timeTravelFrame={timeTravelFrame}
        />
      </ErrorBoundary>

      {timeTravelActive && (
        <TimeTravelBar
          onFrame={setTimeTravelFrame}
          onExit={() => { setTimeTravelActive(false); setTimeTravelFrame([]); }}
        />
      )}


      {/* ── MAP VIEW CONTROLS (3D/2D + SATELLITE TOGGLE) ── */}
      <motion.div
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}
        className="absolute bottom-[75px] md:bottom-[100px] z-[200] flex items-center gap-2 pointer-events-none"
        style={{ left: isMobile ? '12px' : '120px' }}
      >
        {/* 3D/2D Toggle */}
        <button
          onClick={() => setMapProjection(p => p === 'globe' ? 'mercator' : 'globe')}
          className="glass-panel p-3.5 pointer-events-auto hover:border-[var(--gold-primary)]/40 transition-colors group relative"
          title={mapProjection === 'globe' ? 'Switch to 2D Map' : 'Switch to 3D Globe'}
        >
          {mapProjection === 'globe' ? (
            <MapPinned className="w-5 h-5 text-[var(--gold-primary)] group-hover:scale-110 transition-transform" />
          ) : (
            <Globe className="w-5 h-5 text-[var(--cyan-primary)] group-hover:scale-110 transition-transform" />
          )}
          <span className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 text-[9px] font-mono text-[var(--text-muted)] whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity glass-panel px-2 py-1 z-[300]">
            {mapProjection === 'globe' ? '2D MAP' : '3D GLOBE'}
          </span>
        </button>

        {/* Map Style Toggle (satellite imagery is a public tile server: hidden in PIPELINE mode) */}
        {!securedMode && (
          <button
            onClick={() => setMapStyle(s => s === 'dark' ? 'satellite' : 'dark')}
            className="glass-panel p-3.5 pointer-events-auto hover:border-[var(--gold-primary)]/40 transition-colors group relative"
            title={mapStyle === 'dark' ? 'Satellite View' : 'Night View'}
          >
            {mapStyle === 'dark' ? (
              <Satellite className="w-5 h-5 text-[var(--alert-green)] group-hover:scale-110 transition-transform" />
            ) : (
              <Moon className="w-5 h-5 text-[var(--cyan-primary)] group-hover:scale-110 transition-transform" />
            )}
            <span className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 text-[9px] font-mono text-[var(--text-muted)] whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity glass-panel px-2 py-1 z-[300]">
              {mapStyle === 'dark' ? 'SATELLITE' : 'NIGHT MODE'}
            </span>
          </button>
        )}

      </motion.div>

      {/* ── TOP-RIGHT STATUS (desktop) — C2 DISPLAY ── */}
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }} className="status-bar-desktop absolute top-4 right-6 z-[200] pointer-events-none flex items-center gap-4 text-[9px] font-mono tracking-widest text-[var(--text-muted)]">

        <span className="flex items-center gap-1">SYS: <span className={backendStatus === 'connected' ? 'text-[var(--alert-green)]' : 'text-[var(--alert-red)]'}>{backendStatus.toUpperCase()}</span></span>



        <span className="hidden lg:inline-flex items-center gap-1">
          <span className="text-[var(--cyan-primary)] font-bold">{Object.values(activeLayers).filter(Boolean).length}</span>
          <span className="text-[var(--text-muted)]/60">FEEDS</span>
        </span>

        <UptimeClock />

        <RecorderControl />

        <SecuredConnection />

        <button
          onClick={() => { setTimeTravelActive(v => !v); if (timeTravelActive) setTimeTravelFrame([]); }}
          className={`pointer-events-auto glass-panel px-3 py-1.5 flex items-center gap-1.5 text-[8px] font-mono tracking-widest transition-opacity border ${timeTravelActive ? 'border-[#00E5FF]/60 bg-[#00E5FF]/10 text-[#00E5FF]' : 'border-white/10 bg-black/20 text-[var(--text-secondary)] hover:opacity-80'}`}
          title="Replay historical events from the lakehouse"
        >
          <span className="font-bold">⏱ TIME TRAVEL</span>
        </button>

        <a href="/logs" className="pointer-events-auto glass-panel px-3 py-1.5 flex items-center gap-1.5 text-[8px] font-mono tracking-widest hover:opacity-80 transition-opacity border-white/10 bg-black/20">
          <span className="font-bold text-[var(--text-secondary)]">LOGS</span>
        </a>

        <Link href="/llm" className="pointer-events-auto glass-panel px-3 py-1.5 flex items-center gap-1.5 text-[8px] font-mono tracking-widest hover:opacity-80 transition-opacity border-white/10 bg-black/20">
          <span className="font-bold text-[var(--text-secondary)]">LLM</span>
        </Link>


      </motion.div>

      {/* ── MOBILE: Compact top status ── */}
      {isMobile && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }} className="absolute top-3 right-3 z-[200] pointer-events-auto flex items-center gap-2">
          <RecorderControl />
          <SecuredConnection />
          <a href="/logs" className="glass-panel px-2 py-1 flex items-center gap-1.5 text-[7px] font-mono tracking-widest hover:opacity-80 transition-opacity border-white/10 bg-black/20">
            <span className="font-bold text-[var(--text-secondary)]">LOGS</span>
          </a>
          <Link href="/llm" className="glass-panel px-2 py-1 flex items-center gap-1.5 text-[7px] font-mono tracking-widest hover:opacity-80 transition-opacity border-white/10 bg-black/20">
            <span className="font-bold text-[var(--text-secondary)]">LLM</span>
          </Link>
        </motion.div>
      )}



      {/* ── NEW SIDEBAR (Root Level) ── */}
      {showLayers && !isMobile && <LayerPanel data={data} activeLayers={activeLayers} setActiveLayers={setActiveLayers} pipelineMode={securedMode} />}



      {/* ── RIGHT TOOL STRIP (desktop only — mobile uses bottom nav) ── */}
      {!isMobile && <div className="absolute right-2 top-1/2 -translate-y-1/2 flex flex-col gap-2 z-[250] pointer-events-auto bg-black/40 backdrop-blur-sm p-1 rounded-full border border-white/5">
        <div className="relative group">
          <button onClick={() => { setShowAlerts(!showAlerts); setShowEntityGraph(false); }} className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${showAlerts ? 'bg-[#FF3D3D]/20' : 'hover:bg-white/10'}`}>
            <AlertTriangle className={`w-4 h-4 ${showAlerts ? 'text-[#FF3D3D]' : 'text-white/60'}`} />
          </button>
          {/* Alerts Panel Slideout */}
          <AnimatePresence>
            {showAlerts && (
              <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }} className="absolute right-12 top-1/2 -translate-y-1/2 w-80">
                <LiveAlerts data={data} onLocate={(lat, lng) => setFlyToLocation({ lat, lng, ts: Date.now() })} onWatchFeed={(url, name) => { setLiveFeedUrl(url); setLiveFeedName(name); }} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="relative group">
          <button onClick={() => { setShowEntityGraph(!showEntityGraph); setShowAlerts(false); }} className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${showEntityGraph ? 'bg-[#D4AF37]/20' : 'hover:bg-white/10'}`}>
            <Network className={`w-4 h-4 ${showEntityGraph ? 'text-[var(--gold-primary)]' : 'text-white/60'}`} />
          </button>
        </div>

        <div className="relative group">
          <button onClick={() => { setShowDesktopSearch(!showDesktopSearch); setShowAlerts(false); setShowEntityGraph(false); }} className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${showDesktopSearch ? 'bg-[var(--gold-primary)]/20' : 'hover:bg-white/10'}`}>
            <Search className={`w-4 h-4 ${showDesktopSearch ? 'text-[var(--gold-primary)]' : 'text-white/60'}`} />
          </button>
          <AnimatePresence>
            {showDesktopSearch && (
              <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }} className="absolute right-12 top-1/2 -translate-y-1/2 w-80">
                <SearchBar alwaysExpanded onLocate={(lat, lng, zoom) => { setFlyToLocation({ lat, lng, zoom, ts: Date.now() }); setShowDesktopSearch(false); }} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>


      </div>}

      {/* ── LIVE FEED VIEWER OVERLAY ── */}
      <AnimatePresence>
        {liveFeedUrl && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className="fixed inset-0 z-[500] flex items-center justify-center bg-black/70 backdrop-blur-sm"
            onClick={() => setLiveFeedUrl(null)}
          >
            <motion.div
              initial={{ y: 20 }}
              animate={{ y: 0 }}
              className="w-[90vw] max-w-[900px] flex flex-col relative rounded-xl overflow-hidden border border-[var(--border-primary)] shadow-2xl bg-black"
              onClick={e => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-2.5 bg-[#111] border-b border-[var(--border-primary)]">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-[#FF4081] animate-horus-pulse" />
                  <span className="text-[12px] font-mono font-bold text-white tracking-wider">{liveFeedName}</span>
                  <span className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 font-mono text-[9px] font-bold">LIVE STREAM</span>
                  {!liveFeedEmbedAllowed && (
                    <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 font-mono text-[9px]">EXTERNAL ONLY</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <a
                    href={getYouTubeWatchUrl(liveFeedUrl)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[var(--border-primary)] hover:bg-[var(--gold-primary)] hover:text-black text-white transition-colors text-[11px] font-mono"
                  >
                    <span>Open in YouTube</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                  <button onClick={() => setLiveFeedUrl(null)} className="text-white/70 hover:text-white transition-colors p-1">
                    <X className="w-5 h-5" />
                  </button>
                </div>
              </div>

              {/* Body — iframe or external card */}
              {liveFeedEmbedAllowed ? (
                <div className="w-full aspect-video relative bg-black">
                  <iframe
                    src={liveFeedUrl}
                    className="w-full h-full absolute inset-0"
                    allow="autoplay; encrypted-media"
                    allowFullScreen
                  />
                </div>
              ) : (
                <div className="w-full aspect-video flex items-center justify-center bg-black/95">
                  <div className="text-center px-8">
                    <div className="w-14 h-14 rounded-full bg-[#39FF14]/10 border border-[#39FF14]/20 flex items-center justify-center mx-auto mb-4">
                      <ExternalLink className="w-6 h-6 text-[#39FF14]" />
                    </div>
                    <p className="text-[13px] font-mono font-bold text-white tracking-widest mb-2">EMBED RESTRICTED</p>
                    <p className="text-[11px] font-mono text-white/50 mb-6 max-w-xs">
                      {liveFeedName} does not allow third-party embedding. Click below to open the live stream directly.
                    </p>
                    <a
                      href={getYouTubeWatchUrl(liveFeedUrl)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 px-6 py-2.5 rounded border border-[#39FF14]/40 text-[#39FF14] font-mono text-[12px] hover:bg-[#39FF14]/10 transition-colors tracking-wider"
                    >
                      <ExternalLink className="w-4 h-4" />
                      OPEN LIVE STREAM
                    </a>
                  </div>
                </div>
              )}

              {/* Footer — only show for embeddable feeds */}
              {liveFeedEmbedAllowed && (
                <div className="bg-[#111]/90 px-4 py-2.5 border-t border-[var(--border-primary)] flex items-center gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-[var(--gold-primary)] shrink-0" />
                  <span className="text-[11px] font-mono text-white/70 leading-relaxed">
                    If you see &ldquo;Video unavailable&rdquo;, use <strong className="text-[var(--gold-primary)]">Open in YouTube</strong> above.
                  </span>
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══ MOBILE UI ═══ */}
      {isMobile && (
        <>
          {/* Mobile Bottom Navigation */}
          <div className="mobile-nav">
            <div className="glass-panel mobile-nav-inner">
              {[
                { id: 'layers' as const, icon: Layers, label: 'LAYERS' },
                { id: 'intel' as const, icon: Newspaper, label: 'INTEL' },
                { id: 'search' as const, icon: Search, label: 'SEARCH' },
              ].map(tab => (
                <button key={tab.id} onClick={() => setMobilePanel(mobilePanel === tab.id ? null : tab.id)}
                  className={`mobile-nav-btn ${mobilePanel === tab.id ? 'active' : ''}`}>
                  <tab.icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Mobile Drawer */}
          <AnimatePresence>
            {mobilePanel && (
              <motion.div
                initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }}
                transition={{ type: 'spring', damping: 30, stiffness: 300 }}
                className="fixed bottom-[52px] left-0 right-0 z-[400] glass-panel rounded-b-none overflow-y-auto styled-scrollbar"
                style={{ maxHeight: 'min(55vh, calc(100dvh - 100px))', paddingBottom: 'env(safe-area-inset-bottom, 4px)' }}
              >
                <div className="mobile-drawer-handle" />
                <div className="px-3 pb-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="hud-text text-[9px] text-[var(--text-primary)]">
                      {mobilePanel === 'layers' ? 'LAYERS & STATS' : mobilePanel === 'intel' ? 'INTEL FEED' : 'SEARCH'}
                    </span>
                    <button onClick={() => setMobilePanel(null)} className="text-[var(--text-muted)] p-1"><X className="w-4 h-4" /></button>
                  </div>
                  {mobilePanel === 'layers' && (
                    <>
                      <div className="glass-panel-sm p-2 mb-2">
                        <div className="grid grid-cols-5 gap-1 text-center">
                          <div><div className="hud-label" style={{fontSize:'6px'}}>AIR</div><div className="hud-value text-[9px]">{totalFlights.toLocaleString()}</div></div>
                          <div><div className="hud-label" style={{fontSize:'6px'}}>SAT</div><div className="hud-value text-[9px]">{(data.satellites?.length||0)}</div></div>
                          <div><div className="hud-label" style={{fontSize:'6px'}}>CAM</div><div className="hud-value text-[9px]">{(data.cameras?.length||0)}</div></div>
                          <div><div className="hud-label" style={{fontSize:'6px'}}>WX</div><div className="hud-value text-[9px]" style={{color:'var(--accent-weather)'}}>{(data.weather_events?.length||0)}</div></div>
                          <div><div className="hud-label" style={{fontSize:'6px'}}>NUC</div><div className="hud-value text-[9px]" style={{color:'var(--accent-nuclear)'}}>{(data.infrastructure?.length||0)}</div></div>
                        </div>
                      </div>
                      <LayerPanel data={data} activeLayers={activeLayers} setActiveLayers={setActiveLayers} pipelineMode={securedMode} isMobile={true} />
                      <div className="mt-8">
                        <ViewPresets onNavigate={(lat, lng, zoom) => { setFlyToLocation({ lat, lng, ts: Date.now() }); setMapView(v => ({ ...v, zoom })); setMobilePanel(null); }} />
                      </div>
                    </>
                  )}
                  {mobilePanel === 'intel' && <IntelFeed data={data} onLocate={(lat, lng) => { setFlyToLocation({ lat, lng, ts: Date.now() }); setMobilePanel(null); }} />}
                  {mobilePanel === 'search' && (
                    <div className="space-y-2">
                      <SearchBar onLocate={(lat, lng, zoom) => { setFlyToLocation({ lat, lng, zoom, ts: Date.now() }); setMobilePanel(null); }} />
                      <SharePanel mapView={mapView} activeLayers={activeLayers} mouseCoords={null} />
                    </div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}

      {/* ── BOTTOM RAW METRICS (desktop) ── */}
      {!isMobile && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3, duration: 0.8 }} className="desktop-only absolute bottom-8 z-[200] pointer-events-auto" style={{ left: '120px' }}>
          <div className="flex items-center gap-6 text-[8px] font-mono tracking-widest text-[var(--text-muted)] opacity-60">
            <div className="flex gap-2 items-center">
              <span>COORD</span>
              <span ref={coordsDisplayRef} className="text-[var(--gold-primary)] font-bold tabular-nums">—</span>
            </div>
            {!securedMode && (
              <div className="flex gap-2 items-center">
                <span>LOC</span>
                <span className="text-[var(--cyan-primary)] truncate max-w-[200px]">{locationLabel || 'HOVER MAP'}</span>
              </div>
            )}
            <div className="flex gap-2 items-center">
              <span>Z</span>
              <span className="text-[var(--gold-primary)] font-bold tabular-nums">{mapView.zoom.toFixed(1)}</span>
            </div>
          </div>
        </motion.div>
      )}

      {/* ── Scale Bar (desktop) ── */}
      <div className="desktop-only absolute bottom-[4.5rem] left-[20rem] z-[201] pointer-events-none">
        <ScaleBar zoom={mapView.zoom} latitude={mapView.latitude} />
      </div>

      {/* ── Region Dossier ── */}
      {(regionDossier || dossierLoading) && (
        <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="absolute top-16 md:top-20 left-2 right-2 md:left-1/2 md:right-auto md:-translate-x-1/2 z-[300] md:w-[480px] max-h-[65vh] overflow-y-auto styled-scrollbar">
          <div className="glass-panel p-5 horus-glow">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-mono font-bold text-[var(--gold-primary)] tracking-wider">REGION DOSSIER</h2>
              <button onClick={() => { setRegionDossier(null); setDossierLoading(false); }} className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-xs">✕</button>
            </div>
            {dossierLoading ? (
              <div className="text-center py-8">
                <div className="w-5 h-5 border-2 border-[var(--gold-primary)] border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                <span className="text-[8px] font-mono text-[var(--text-muted)] tracking-widest">COMPILING INTEL...</span>
              </div>
            ) : regionDossier && (
              <div className="space-y-3">
                <div><div className="hud-label mb-0.5">LOCATION</div><div className="text-xs text-[var(--text-primary)]">{regionDossier.location?.display_name}</div></div>
                {regionDossier.country && (
                  <div className="grid grid-cols-2 gap-2">
                    <div><div className="hud-label mb-0.5">COUNTRY</div><div className="text-xs text-[var(--text-primary)]">{regionDossier.country.flag} {regionDossier.country.name}</div></div>
                    <div><div className="hud-label mb-0.5">CAPITAL</div><div className="text-xs text-[var(--text-primary)]">{regionDossier.country.capital}</div></div>
                    <div><div className="hud-label mb-0.5">POPULATION</div><div className="text-xs text-[var(--text-primary)]">{regionDossier.country.population?.toLocaleString()}</div></div>
                    <div><div className="hud-label mb-0.5">REGION</div><div className="text-xs text-[var(--text-primary)]">{regionDossier.country.subregion || regionDossier.country.region}</div></div>
                    <div><div className="hud-label mb-0.5">LANGUAGES</div><div className="text-xs text-[var(--text-primary)]">{regionDossier.country.languages?.join(', ')}</div></div>
                    <div><div className="hud-label mb-0.5">AREA</div><div className="text-xs text-[var(--text-primary)]">{regionDossier.country.area?.toLocaleString()} km²</div></div>
                  </div>
                )}
                {regionDossier.head_of_state && (<div><div className="hud-label mb-0.5">HEAD OF STATE</div><div className="text-xs text-[var(--gold-primary)]">{regionDossier.head_of_state.name}</div><div className="text-[8px] text-[var(--text-muted)]">{regionDossier.head_of_state.position}</div></div>)}
                {regionDossier.wikipedia && (<div><div className="hud-label mb-1">INTELLIGENCE BRIEF</div><div className="flex gap-3">{regionDossier.wikipedia.thumbnail && <img src={regionDossier.wikipedia.thumbnail} alt="" className="w-14 h-14 rounded object-cover flex-shrink-0" />}<p className="text-[8px] text-[var(--text-secondary)] leading-relaxed">{regionDossier.wikipedia.extract}</p></div></div>)}
              </div>
            )}
          </div>
        </motion.div>
      )}

      {/* ── Camera Viewer ── */}
      <CameraViewer
        camera={activeCamera}
        onClose={() => setActiveCamera(null)}
        onLocate={(lat, lng) => setFlyToLocation({ lat, lng, ts: Date.now() })}
      />

      {/* ── Entity Graph Panel ── */}
      {showEntityGraph && (
        <EntityGraphPanel
          entity={entityGraphTarget}
          onClose={() => setShowEntityGraph(false)}
        />
      )}

      {/* ── OVERLAYS ── */}
      <div className="vignette absolute inset-0 pointer-events-none z-[2]" />
      <div className="crt-scanlines absolute inset-0 pointer-events-none z-[3] opacity-[0.02]" />
      {/* Corner frames — using explicit classes for Tailwind JIT compatibility */}
      {[
        { pos: 'top-0 left-0', vAnchor: 'top-0', hAnchor: 'left-0', hGrad: 'bg-gradient-to-r', vGrad: 'bg-gradient-to-b' },
        { pos: 'top-0 right-0', vAnchor: 'top-0', hAnchor: 'right-0', hGrad: 'bg-gradient-to-l', vGrad: 'bg-gradient-to-b' },
        { pos: 'bottom-0 left-0', vAnchor: 'bottom-0', hAnchor: 'left-0', hGrad: 'bg-gradient-to-r', vGrad: 'bg-gradient-to-t' },
        { pos: 'bottom-0 right-0', vAnchor: 'bottom-0', hAnchor: 'right-0', hGrad: 'bg-gradient-to-l', vGrad: 'bg-gradient-to-t' },
      ].map((c, i) => (
        <div key={i} className={`absolute ${c.pos} w-16 h-16 pointer-events-none z-[1]`}>
          <div className={`absolute ${c.vAnchor} ${c.hAnchor} w-full h-[1px] ${c.hGrad} from-[var(--gold-primary)]/30 to-transparent`} />
          <div className={`absolute ${c.vAnchor} ${c.hAnchor} w-[1px] h-full ${c.vGrad} from-[var(--gold-primary)]/30 to-transparent`} />
        </div>
      ))}

      {/* Keyboard Shortcuts Overlay */}
      <KeyboardShortcuts />


      {/* Shortcut hint */}
      <div className="desktop-only absolute bottom-[26px] right-5 z-[200] pointer-events-none text-[6px] font-mono text-[var(--text-muted)]/40 tracking-widest">
        [?] SHORTCUTS · [F] FULLSCREEN · [S] SHARE · [R] RESET VIEW
      </div>


    </main>
  );
}
