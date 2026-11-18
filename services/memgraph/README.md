# Horus Memgraph

This is the knowledge graph behind the intel layer: organisations, vessels,
places and countries from Wikidata, with their ownership and location links. It
runs Memgraph inside the Application and exposes a small HTTP shim. Bolt stays
on localhost.

| | |
|---|---|
| Workbench Application script | `horus/services/memgraph/app.py` |
| Runtime | Horus Memgraph (`horus-memgraph-runtime`, Memgraph 3.11.0) |
| Resource profile | 2 vCPU / 8 GiB is ample (see sizing) |
| Env vars | none. Set `MEMGRAPH_API_TOKEN` to require `Authorization: Bearer <token>` on `/cypher` |
| Endpoints | `GET /`, `GET /health`, `POST /cypher` with `{"query": "...", "params": {...}}` |
| Data | `/home/cdsw/memgraph-data`: snapshots and WAL. It survives restarts. |

## Load the graph from the base snapshot

The base graph ships as a snapshot archive, `osiris-graph-base-20260705.tgz`
(about 100 MB, containing three identical 233 MB snapshots). It is too large for
git, so it is uploaded out of band. Restoring it takes about a minute.

1. Upload the archive to the Workbench project, for example to `/home/cdsw/`.
2. Before the first start of the Application, open a Session terminal in
   the same project and run:
   ```bash
   mkdir -p /home/cdsw/memgraph-data
   tar xzf /home/cdsw/osiris-graph-base-20260705.tgz -C /home/cdsw/memgraph-data
   ls /home/cdsw/memgraph-data/snapshots/      # three snapshot files
   ```
3. Start the Application. Memgraph recovers the newest snapshot on boot.
4. Verify:
   ```bash
   curl -s https://<subdomain>.<domain>/cypher -H 'Content-Type: application/json' \
     -d '{"query":"MATCH (n) RETURN count(n) AS n"}'        # 949256
   ```

The snapshot was verified on 2026-11-17 with `horus-memgraph-runtime:1.0.0`.
It recovered 949,256 nodes and 1,338,428 edges:
- nodes: Organization 797,532, Vessel 91,177, Place 59,867, Country 680
- edges: COUNTRY 728,256, HEADQUARTERED_IN 558,030, SUBSIDIARY_OF 28,969,
  MANUFACTURED_BY 23,173
- 9 label and property indexes

Snapshots are tied to a Memgraph version. If the runtime's
`MEMGRAPH_VERSION` changes, test the restore before upgrading.

The scripts that originally built the graph from `nohumans.ndjson.gz`
(`project.py` and `load.py`) are not in the OSIRIS repo. The snapshot is the
only fast restore path, so keep the archive safe.

## Sizing

With the base graph loaded, Memgraph uses about 590 MiB resident and about
480 MiB tracked. OSIRIS sized this Application at 16 GiB or more, but that
headroom is only needed for large bulk loads (for example, adding the OFAC
sanctions graph). A standard 8 GiB profile is plenty for serving.

## Take a new snapshot

```bash
curl -s https://<subdomain>.<domain>/cypher -H 'Content-Type: application/json' \
  -d '{"query":"CREATE SNAPSHOT;"}'
tar czf /home/cdsw/horus-graph-$(date +%Y%m%d).tgz -C /home/cdsw/memgraph-data snapshots
```
