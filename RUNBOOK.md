# Horus backend — CDP Public Cloud Data Hubs

The Horus streaming backend: NiFi → Kafka → Flink (SSB) → Iceberg, read back
through Impala, with the Feeds-Gateway switchable between **live** and
**lakehouse** sources.

Status: the gateway was run locally against a simulated lake. The NiFi flows and
SSB SQL were carried over from the predecessor project (OSIRIS) and have **not**
been imported or run on a cluster yet. Treat the first import as the test.

## Repo layout

| Path | What |
|---|---|
| `nifi/` | Six NiFi flow definitions, one per feed |
| `ssb/` | Iceberg DDL, the Kafka → Iceberg job, Impala checks |
| `services/feeds-gateway/` | Feeds-Gateway (Cloudera AI application) |
| `tools/parameterize_flows.py` | Re-run after exporting a flow from NiFi, before committing |
| `horus.env.example` | Gateway environment variables |

Large data files (`*.ndjson.gz` graph dump, `*.tgz` Memgraph snapshots) are
gitignored; keep them outside git.

## Names used

| Thing | Value |
|---|---|
| Kafka topic | `horus-events` |
| Database / table | `horus.events_iceberg` |
| NiFi parameter context | `Horus` |
| Gateway consumer group | `horus-feeds-gateway` |
| Flink consumer group | `horus-flink-lakehouse` |

## 0. Before you start

- Change the workload password for the account that was hardcoded in the
  predecessor OSIRIS repo, and issue a new aisstream.io API key. Both are in
  that repo's public git history.
- Data Hubs needed in one environment (same Data Lake):
  **Flow Management** (NiFi 2.x), **Streams Messaging**, **Streaming Analytics**
  (SSB), and a **Data Mart** (Impala).
- A workload user with a workload password set, synced to the environment.

## 1. Kafka (Streams Messaging)

Create the topic in Streams Messaging Manager, or from a broker node:

    kafka-topics --create --topic horus-events --partitions 3 --replication-factor 3 \
      --bootstrap-server <broker0>:9093 --command-config client.properties

Ranger (Kafka service, `cm_kafka`):

| Principal | Access |
|---|---|
| workload user (NiFi publishes as this user) | Publish, Describe on `horus-events` |
| workload user (gateway) | Consume on `horus-events`; consumer group `horus-feeds-gateway` |
| `ssb` | Consume on `horus-events`; consumer group `horus-flink-lakehouse`; Publish on `ATLAS_HOOK` |

The flows publish with **Transactions Enabled = true**, so the publishing user
also needs transactional-id access (Ranger resource *transactionalid*, `*`).

## 2. NiFi (Flow Management)

1. Create the parameter context first: **Parameter Contexts → +**, name it
   exactly `Horus`, and add:

   | Parameter | Sensitive | Value |
   |---|---|---|
   | `kafka.bootstrap.servers` | no | all brokers, `host:9093` comma-separated |
   | `kafka.sasl.username` | no | workload user |
   | `kafka.sasl.password` | **yes** | workload password |
   | `kafka.topic` | no | `horus-events` |
   | `aisstream.api.key` | no | the new aisstream key |
   | `http.contact` | no | an email or URL; sent in the User-Agent to adsb.lol and NWS |

2. For each file in `nifi/`: drag a Process Group onto the canvas → **Browse**
   → upload the JSON. Each one binds to the `Horus` context. If NiFi creates
   `Horus (1)` instead of reusing yours, re-bind the group to `Horus` in its
   configuration and delete the copy.
3. In each group: enable the controller services (Kafka connection, and the SSL
   context where present), then start the processors.
4. The two weather flows carry an SSL context pointing at
   `/hadoopfs/fs4/working-dir/cm-auto-global_truststore.jks`. That path is the
   Data Hub default; if the service is invalid, switch it to the cluster's
   default NiFi SSL context service.
5. Check: SMM shows messages arriving on `horus-events`; each has
   `entity.entityType` of SEISMIC, FIRE, WEATHER, FLIGHT or VESSEL.

Feed cadence as shipped: earthquakes ~8 min, fires/weather 10 min, flights
5 min across a list of regions, vessels continuous (WebSocket).

## 3. Lakehouse (SSB + Iceberg)

1. In Hue (Impala): `CREATE DATABASE IF NOT EXISTS horus;`
2. Ranger: grant `ssb` and the workload user on database `horus` (Hadoop SQL) and
   on its S3 warehouse path (RAZ / S3 policy). If `ssb` is not in Ranger, add it
   manually.
3. SSB: confirm the Hive catalog is registered; put its name in
   `ssb/01_events_iceberg_ddl.sql` and run it.
4. SSB: open `ssb/02_kafka_to_iceberg.sql`, fill the placeholders in the editor,
   **enable checkpointing** in job settings, run.
5. Hue: run `ssb/03_verify.sql`. Row counts should grow between runs. If new
   rows stop appearing in Impala, `REFRESH horus.events_iceberg;`.

Change from the predecessor: `payload` now stores the **whole** canonical message rather
than a five-field summary. That is what makes lakehouse mode possible, and the
gateway reads `$.entity.name` (falling back to the old `$.name`).

## 4. Feeds-Gateway (Cloudera AI application)

Create a Cloudera AI project from this repo; the gateway lives at
`services/feeds-gateway/`, which is where `gateway_startup.py` looks by default
(`/home/cdsw/services/feeds-gateway`). Create the application with script
`services/feeds-gateway/gateway_startup.py`, Unauthenticated Access ON, and the
variables from `horus.env.example`.

Nothing is hardcoded any more: brokers, user, password and topic all come from
the environment. Without `KAFKA_BROKERS` the gateway still starts and serves
lakehouse mode.

Check:

    curl -s https://<gateway>/health          # "mode": "live", kafka.messages climbing
    curl -s https://<gateway>/feeds/flights   # "source": "streaming-lakehouse"

## 5. Switching between live and lakehouse

| Mode | Where the picture comes from | Needs |
|---|---|---|
| `live` | NiFi pulls the provider APIs → Kafka → gateway | NiFi egress to the providers |
| `lakehouse` | Gateway replays the last `REPLAY_HOURS` of `events_iceberg` through Impala, on a loop | Impala only |

    curl -s -X POST https://<gateway>/mode -H 'Content-Type: application/json' -d '{"mode":"lakehouse"}'
    curl -s https://<gateway>/mode            # replay state, window, position, loop count
    curl -s -X POST https://<gateway>/mode -H 'Content-Type: application/json' -d '{"mode":"live"}'

- Switching clears the gateway's in-memory picture, so the map empties and
  refills from the new source.
- In lakehouse mode `/feeds/*` responses carry `"source": "lakehouse-replay"`.
- Replayed entities keep their original timestamps.
- For a true air-gap demonstration, stop the NiFi process groups as well; the
  gateway ignores Kafka in lakehouse mode but NiFi would still be calling out.
- `REPLAY_SPEED=10` makes a short recording look busy; `REPLAY_HOURS` sets how
  far back the loop reaches.

Not done yet: the map UI still has its original two-position switch
(direct / secured). Wiring a Live / Lakehouse control to `POST /mode` is a UI
change and belongs with the decision about rebasing the UI on upstream.

## 6. Still to do outside this kit

- Memgraph: load `nohumans.ndjson.gz` (the loader scripts named in the on-prem
  guide are not in git), then take a snapshot so the next rebuild is a restore.
- Tile server: place the `.mbtiles` file where `tileserver/config.json` expects it.
- Bring the map UI and the intel service into this repo, named `horus-*`
  (applications, subdomains, UI strings).
