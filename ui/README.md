# Horus UI

The Horus map and analyst UI is a Next.js 16 app. It is derived from
[OSIRIS](https://github.com/simplifaisoul/osiris) (MIT, see [LICENSE](LICENSE)).

| | |
|---|---|
| Workbench Application script | `horus/ui/launch_ui.py` |
| Runtime | Horus Node 22 |
| Resource profile | 4 GiB or more (`next build` runs on first start) |
| Unauthenticated Access | on |

## Env vars

| Variable | Form | Used for |
|---|---|---|
| `FEEDS_GATEWAY_URL` | `https://<gateway>.<domain>`, no trailing slash | live feeds, time travel, entity intel, GraphRAG |
| `INTEL_URL` | `https://<intel>.<domain>`, no trailing slash | entity enrichment (`/resolve`) |
| `TILESERVER_PUBLIC_URL` | `https://<tiles>.<domain>/`, trailing slash | basemap; the style URL `<tiles>/styles/dark/style.json` is derived from it |

The slash rules matter. The UI appends `/resolve` to `INTEL_URL`, so a trailing
slash there gives `//resolve` and a 404.

## Builds

The basemap style URL is compiled into the browser bundle, so the launcher
builds the app itself (`npm ci`, then `next build`) on first start. It rebuilds
when either of these changes:
- the style URL
- the last git commit that touched `ui/`

Set `HORUS_UI_REBUILD=1` to force a rebuild.

The launcher runs `next start`, not Next's standalone output. Standalone output
breaks static chunk serving (`ChunkLoadError`).

## Local development

```bash
cd ui && npm ci
FEEDS_GATEWAY_URL=http://localhost:8091 npm run dev
```

The app needs Node 20.19+, 22.13+ or 24+; Node 23 is not supported. On Apple
Silicon, don't build inside the amd64 runtime image: under Rosetta, Node
starts with `--no-opt`, which `next build` rejects.

## Changes from OSIRIS

- Renamed OSIRIS to Horus, including identifiers, CSS classes and
  localStorage keys.
- Removed the Umami analytics middleware, the public SEO metadata, the sitemap,
  and the crypto/donation promo.
- Postgres logging is opt-in. It is on only when `LOGS_PG_HOST` is set;
  otherwise logs go to the console and to the `/logs` viewer's in-memory
  buffer.
