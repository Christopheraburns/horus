# Installing Horus

This guide deploys one Horus instance into a Cloudera CDP Public Cloud
environment. A team runs it with its own CDP user. There is no shared service
account.

> **Status:** draft. Every step has been verified once, on the first instance
> (`dev`). It has not yet been tried by a second team.

## What gets built

| Piece | Where | Name (instance `dev`) |
|---|---|---|
| Kafka Data Hub | new, Streams Messaging Light Duty | `horus-dev-kafka` |
| Flink Data Hub | new, Streaming Analytics Light Duty | `horus-dev-flink` |
| NiFi flows (7 flows, 5 feeds) | existing Flow Management (NiFi 2) Data Hub | groups `HORUS-dev - …`, parameter context `Horus-dev` |
| Kafka topic | Kafka Data Hub | `horus-dev-events` |
| Iceberg table | existing CDW Trino virtual warehouse | `iceberg.horus_dev.events_iceberg` |
| SSB project and Flink job | Flink Data Hub | project `horus_dev`, job `horus_dev_kafka_to_iceberg` |

Every name comes from `HORUS_INSTANCE`, so teams sharing an environment don't
collide.

The Kafka and Flink Data Hubs are billable while they run.

## Prerequisites

You need:
- A CDP environment with a Data Lake on runtime 7.3.x.
- A running NiFi 2 Flow Management Data Hub.
- A CDW Trino virtual warehouse.
- A Cloudera AI Workbench.

You also need permission to create Data Hubs in the environment.

### Workbench runtimes (admin, once per Workbench)

The Horus Applications run on two custom runtimes, published as public images
on Docker Hub. A Workbench administrator registers them once, in **Site
Administration → Runtime Catalog → Add Runtime**, using the full tags:

| Image | Edition | Used by |
|---|---|---|
| `docker.io/christopheraburns/horus-node-runtime:1.0.0` | Horus Node 22 | UI, intel resolver, tile server |
| `docker.io/christopheraburns/horus-memgraph-runtime:1.0.0` | Horus Memgraph | graph database |

The Dockerfiles are in [runtimes/](../runtimes). To rebuild the images or push
them to another registry, for example one a Workbench without internet access
can reach, run `HORUS_REGISTRY=<registry> runtimes/build.sh --push`.

## 1. Credentials

You need two kinds of credentials.

| Credential | Used for | Where to get it |
|---|---|---|
| CDP API access key | Creating Data Hubs and reading the environment. Needed only while provisioning. | Management Console → your profile → **Generate Access Key** |
| Workload user and password | Kafka, NiFi, SSB and Trino logins at runtime | Management Console → your profile → **Set Workload Password** |

After setting or changing the workload password, sync it to the environment.
In Management Console, open the environment and choose **Actions → Synchronize
Users**. Kafka, NiFi and Trino keep rejecting the new password with *Invalid
username or password* or HTTP 401 until the sync has run.

## 2. Workbench project

1. Create a project in your Workbench from the Horus git repository.
2. In **Project Settings → Advanced**, set the variables listed in
   [`horus.env.example`](../horus.env.example): `CDP_ACCESS_KEY_ID`,
   `CDP_PRIVATE_KEY`, `HORUS_INSTANCE`, `HORUS_ENVIRONMENT`,
   `HORUS_NIFI_DATAHUB`, `HORUS_LAKE_VW`, `HORUS_WORKLOAD_USER`,
   `HORUS_WORKLOAD_PASSWORD`, `HORUS_AISSTREAM_API_KEY`, `HORUS_HTTP_CONTACT`,
   `HORUS_OPENSKY_CLIENT_ID` and `HORUS_OPENSKY_CLIENT_SECRET`.
3. Start a session and open a terminal. The repo lives at `/home/cdsw/horus`.
   Run every command below from there, and give Application scripts paths
   that start with `horus/`, for example
   `horus/services/tileserver/serve-tiles.py`. The Kafka brokers are only
   reachable from inside the CDP network, so run the provisioner from
   Workbench, not from a laptop.

```bash
pip install -r provision/requirements.txt
python provision/horus.py status        # read-only; shows what exists and what create would do
```

Project variables override any `.env` file. After changing them, start a new
session so it picks up the new values.

## 3. Create the Data Hubs

```bash
python provision/horus.py create        # dry run: prints the plan
python provision/horus.py create --yes --wait
```

This creates the Kafka and Flink Data Hubs, which takes about an hour, and
then builds the data plane (steps 4 to 7). Re-running it is safe, because
anything that already exists is skipped.

## 4. Kafka topic

`create --yes` creates `horus-<instance>-events` with 3 partitions.

If you are not allowed to create topics, the provisioner prints the Ranger
Kafka policy you need.

## 5. Lakehouse table

`create --yes` creates `iceberg.horus_<instance>.events_iceberg` (Iceberg v2,
Parquet) through the Trino virtual warehouse. The table stays empty until the
Flink job is running.

## 6. NiFi flows

`create --yes` does four things here:

1. Creates the `Horus-<instance>` parameter context.
2. Imports the feed flows (one per `nifi/HORUS_*.json`).
3. Enables their controller services.
4. Starts the flows, but only if the Kafka topic step succeeded.

Flights come from two flows:

| Flow | Source | Rate | Notes |
|---|---|---|---|
| `Flights (OpenSky)` | `opensky-network.org/api/states/all`, the whole world in one call | every 90 seconds, about 3,840 of a standard account's 4,000 daily credits | Needs an OpenSky account. On the account page, create an **API client**, then set `HORUS_OPENSKY_CLIENT_ID` and `HORUS_OPENSKY_CLIENT_SECRET`. A standard account is for non-commercial use; OpenSky sells a licensed tier for commercial use. |
| `Flights (adsb.lol)` | six 250 NM circles around major hubs | every 12 minutes, 13:00–03:48 UTC (7 AM–10 PM US Central), about 450 requests a day | Anonymous; adsb.lol allows 500 requests per UTC day per IP (resets 00:00 UTC). The schedule is CRON-driven in the NiFi server's time zone (UTC on Data Hub nodes); change the hours to suit your team. It adds aircraft type and registration, which OpenSky's live data lacks. |

Both publish to the same topic. The live map keeps the newest position per
aircraft. The lake keeps both, tagged by `source_provider`.

Re-running `create --yes` doesn't change flows that already exist in NiFi. To
pick up a changed flow, delete its process group in NiFi first (stop it and
empty its queues), then re-run.

## 7. Ranger policies (manual, once per instance)

The Flink job needs two policies in the Data Lake's Ranger. Create them in
Management Console → environment → Data Lake → **Ranger**. If either is
missing, the provisioner stops and prints the exact policy to add.

S3 policy paths must start with `/` and must not end in `/*`; use the
**recursive** switch instead. The built-in policies are written the same way,
for example `/data/flink`. A path without the leading slash saves without
error but never matches, so access is still denied.

| Ranger service | Resource | User | Permissions | Why |
|---|---|---|---|---|
| Hadoop SQL (`cm_hive`) | database `horus_<instance>`, table `*`, column `*` | `ssb` | All | SSB reads the table definition from the metastore. |
| S3 (`cm_s3`) | the warehouse bucket, path `/data/warehouse/tablespace/external/hive/horus_<instance>.db`, recursive | your workload user and `ssb` | read, write | The environment uses RAZ, so S3 access is decided by Ranger. SSB (as `ssb`) reads the table metadata when it plans the job, and the job (as you) writes the data files. |

## 8. Flink job

`create --yes` does three things here:

1. Unlocks your SSB keytab. SSB runs jobs as you, from a keytab derived from
   your workload password.
2. Creates the SSB project `horus_<instance>`.
3. Submits [ssb/02_kafka_to_iceberg.sql](../ssb/02_kafka_to_iceberg.sql) as a
   streaming job with exactly-once checkpointing every 60 seconds. Iceberg
   commits data only on a checkpoint, so expect rows about a minute after the
   job starts.

The job removes duplicates as it writes. It keeps the first row for each
(`event_id`, `event_time`) pair it sees in a 36-hour window and drops the
rest. This removes the repeats that polled feeds produce: earthquakes, fires
and weather alerts are re-sent on every poll. A moving asset's new positions
have new keys and are kept.

### Rebuilding the lake

The lake can be rebuilt from Kafka for as long as the topic still holds the
data. Topic retention is 7 days by default. To rebuild:

1. Stop the job in SSB.
2. Run `DELETE FROM iceberg.horus_<instance>.events_iceberg` in Trino.
3. Bump the consumer-group suffix in `lakehouse_group` in
   [provision/config.py](../provision/config.py).
4. Re-run `create --yes`.

The new consumer group starts from the oldest message in the topic.

Check the result:

```bash
python provision/horus.py status
```

Every row should be OK. `lake table` should show a growing row count.

## 9. Workbench Applications

Each part of Horus that people use runs as a Workbench Application in the
project. For every Application, set these:

- **Unauthenticated Access: on.** The UI's server-side proxy calls the other
  Applications without an Authorization header.
- **Script paths start with `horus/`,** because the repo is at `/home/cdsw/horus`.
- **Env vars are inherited from the project,** so the workload credentials don't
  need to be set again.

Create them in this order. The UI needs the URLs of the others.

| Application | Script | Runtime | Env vars | Check |
|---|---|---|---|---|
| Tile server | `horus/services/tileserver/serve-tiles.py` | Horus Node 22 | `TILESERVER_PUBLIC_URL=https://<tiles>.<domain>/`: this Application's **own** URL, with a trailing slash. A wrong host breaks every glyph, sprite and tile URL in the style. | `/styles/dark/style.json` loads, and every URL in it starts with the tile server's own host |
| Feeds-gateway | `horus/services/feeds-gateway/gateway_startup.py` | PBJ Workbench Python 3.12 | the "Feeds-Gateway variables" that `status` prints, copied exactly; `INTEL_URL=https://<intel>.<domain>` (no slash); the LLM variables below | `/health` lists all five feeds and `kafka.messages` climbs |
| Intel resolver | `horus/services/intel/launch_intel_resolver.py` | Horus Node 22 | `MEMGRAPH_URL=https://<graph>.<domain>/cypher` (optional) | `/health` shows about 20,000 `sanctions_entries` |
| Memgraph | `horus/services/memgraph/app.py` | Horus Memgraph | none | `MATCH (n) RETURN count(n)` returns 949256 |
| UI | `horus/ui/launch_ui.py` | Horus Node 22 | `FEEDS_GATEWAY_URL=https://<gateway>.<domain>` (no slash), `INTEL_URL=https://<intel>.<domain>` (no slash), `TILESERVER_PUBLIC_URL=https://<tiles>.<domain>/` (trailing slash) | the map loads with the dark basemap |

The UI builds itself on first start: `npm ci`, then `next build`. This takes
about 5 minutes, and the Application shows *Starting* until it finishes. The
basemap URL is compiled into the build. The next start rebuilds the UI if
`TILESERVER_PUBLIC_URL` has changed, or if a `git pull` has brought in changes
to `ui/`. Set `HORUS_UI_REBUILD=1` to force a rebuild. Give the UI a profile
with at least 4 GiB, because `next build` uses a lot of memory.

### LLM (Mistral)

The feeds-gateway serves every AI feature in Horus: the `/llm` page, Ask Horus
(GraphRAG) and pattern-of-life. Set these on the feeds-gateway Application:

| Variable | Value |
|---|---|
| `LLM_BASE_URL` | `https://api.mistral.ai/v1` (Mistral Studio) |
| `LLM_API_KEY` | a Mistral API key from Mistral Studio |
| `LLM_MODEL` | `mistral-large-4` (the default) |
| `LLM_REASONING_EFFORT` | optional: `none` for faster answers, `high` to force reasoning |

For an air-gapped environment, keep the same variables and point them at the
on-prem endpoint: Mistral deployed on-prem, or a Mistral model served by
Cloudera AI Inference. Mistral's API is OpenAI-compatible, so nothing else
changes. Check `GET <LLM_BASE_URL>/models` for the exact model ID the endpoint
expects. The UI holds no LLM keys.

Check: the gateway's `/llm/health` shows `"provider": "openai"`, the model, and
`"ollama": true`. That field name is historical; it means the LLM endpoint is
reachable.

Some Applications need files that are too large for git. Upload these to the
project before starting them:

- **Tile server:** `horus-basemap.mbtiles` (214 MB) goes into
  `horus/services/tileserver/`.
- **Memgraph:** extract the graph snapshot archive into `/home/cdsw/memgraph-data`
  before the first start. See [services/memgraph/README.md](../services/memgraph/README.md).

Run `python provision/horus.py status` in a session before starting the
gateway. It writes `/home/cdsw/horus/horus-ca.pem`, the environment certificate
the gateway needs to trust the Kafka brokers.

## 10. Clean up credentials

Once provisioning is done, delete `CDP_ACCESS_KEY_ID` and `CDP_PRIVATE_KEY`
from the Workbench project. The running system needs only the workload user
and password.

If your password policy expires the workload password, update it in the
places it is stored: the project variables, the NiFi parameter context, the
SSB keytab and the Flink job. To do that, re-run `create --yes`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `No credentials found anywhere in chain` (laptop) | `~/.cdp/credentials` has no `[default]` section. Set `CDP_PROFILE`, or rename your section to `[default]`. |
| Kafka *Invalid username or password*, or Trino/NiFi HTTP 401 | The workload password is wrong or not synced (step 1). |
| `kafka: brokers unreachable` | You are running from outside the CDP network. Run from Workbench. |
| SSB `Kerberos keytab needs to be unlocked` | Re-run `create --yes`, which unlocks the keytab. |
| SSB `Failed to open input stream for file: s3a://…` | The Ranger S3 policy is missing, doesn't list `ssb`, or has a path without the leading `/` (step 7). Ranger → **Audits** shows the denied user and path. |
| `status` shows the `lake table` row as WARN with 0 rows | Normal until the Flink job has completed its first checkpoint. |
| Map is blank in both SOURCE modes; browser console shows *blocked by CORS policy* for `style.json` | The tile server is running with `--no-cors`. The current launcher sends CORS headers by default; restart the tile server after `git pull`. |
| Map is blank; `style.json` loads but glyph, sprite or tile requests go to a different host | The tile server's `TILESERVER_PUBLIC_URL` isn't its own URL. Fix it on the tile server Application and restart. |
