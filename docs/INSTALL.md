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
| Kafka topics | Kafka Data Hub | `horus-dev-events`, `horus-dev-alerts` |
| Iceberg table | existing CDW Trino virtual warehouse | `iceberg.horus_dev.events_iceberg` |
| SSB project and Flink jobs | Flink Data Hub | project `horus_dev`, jobs `horus_dev_kafka_to_iceberg` and `horus_dev_detections` |

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

`create --yes` creates `horus-<instance>-events` (every feed),
`horus-<instance>-alerts` (detections) and `horus-<instance>-raw` (every upstream
response as received, for the bronze table: 16 MB messages, 3 days' retention),
each with 3 partitions.

If you are not allowed to create topics, the provisioner prints the Ranger
Kafka policy you need.

## 5. Lakehouse table

`create --yes` creates `iceberg.horus_<instance>.events_iceberg` through the
Trino virtual warehouse: lake schema v2 ([LAKE-SCHEMA.md](LAKE-SCHEMA.md)),
Iceberg format v2, Parquet with zstd, partitioned by day and sorted by map tile.
The table stays empty until the Flink job is running.

It also creates the bronze table `raw_responses` beside it: every upstream
response as NiFi received it, kept 30 days (`RAW_RETENTION_DAYS` on the
maintenance Job), so `events` can be rebuilt after a NiFi script bug
([LAKE-SCHEMA.md](LAKE-SCHEMA.md#raw-capture-the-bronze-table-burndown-17)). Its
Flink job is `horus_<instance>_raw_to_iceberg`.

If the provisioner says the table's codec is not zstd and Trino cannot change it,
run the Impala statement it prints once.

An instance created before schema v2 keeps its v1 table: `create --yes` leaves it
and its running Flink job alone, and does not submit the v2 job onto it. To move
it to v2 with its history:

1. `python provision/horus.py update-scripts --yes`, so NiFi already sends
   envelope v2.
2. `python provision/horus.py migrate-lake` shows the plan; `migrate-lake --yes`
   runs it. It stops the lake job, copies the table into a v2 table a day at a
   time, checks the counts, renames the tables (the old one is kept as
   `events_iceberg_v1`), and starts the v2 job, which resumes from its committed
   Kafka offsets. NiFi keeps publishing throughout; nothing is lost. Every step is
   safe to re-run if one fails.
3. Check Time Travel and Pattern of Life. Drop `events_iceberg_v1` after a week.

**Maintenance.** The Flink job writes many small files (about 1,300 a day). The
Workbench Job `horus-<instance>-lake-maintenance` (created by `create --yes`, or
by the first `maintain-lake --yes`) runs daily at 03:30 UTC: it compacts each
finished day into a few files sorted by map tile, so area queries skip most of
the data, then expires snapshots and orphan files older than 7 days.
`python provision/horus.py maintain-lake` shows what it would do. If the Job
can't be created through the Workbench API, the command prints the settings to
create it by hand.

## 6. NiFi flows

`create --yes` does five things here:

1. Creates the `Horus-<instance>` parameter context.
2. Imports the feed flows (one per `nifi/HORUS_*.json`).
3. Enables their controller services.
4. Starts the flows, but only if the Kafka topic step succeeded.
5. Adds the raw capture branch to flows imported before it existed: a second
   PublishKafka, "Publish raw response", fed from the same response as the
   transform, to the raw topic. It's added through the NiFi API, so the flow's
   state and queues are kept, and started if the flow is running.

Flights come from two flows:

| Flow | Source | Rate | Notes |
|---|---|---|---|
| `Flights (OpenSky)`, **off by default** | `opensky-network.org/api/states/all`, the whole world in one call | every 90 seconds, about 3,840 of a standard account's 4,000 daily credits | OpenSky blocks cloud-provider addresses: from AWS the token request times out. Imported and started only when `HORUS_ENABLE_OPENSKY=1` (for on-prem or non-cloud NiFi). Needs an OpenSky account. On the account page, create an **API client**, then set `HORUS_OPENSKY_CLIENT_ID` and `HORUS_OPENSKY_CLIENT_SECRET`. A standard account is for non-commercial use; OpenSky sells a licensed tier for commercial use. |
| `Flights (adsb.lol)` | six 250 NM circles around major hubs | every 12 minutes, 13:00–03:48 UTC (7 AM–10 PM US Central), about 450 requests a day | Anonymous; adsb.lol allows 500 requests per UTC day per IP (resets 00:00 UTC). The schedule is CRON-driven in the NiFi server's time zone (UTC on Data Hub nodes); change the hours to suit your team. It adds aircraft type and registration, which OpenSky's live data lacks. |

When both run, they publish to the same topic. The live map keeps the newest position per
aircraft. The lake keeps both, tagged by `source_provider`.

Re-running `create --yes` doesn't change flows that already exist in NiFi, apart
from adding the raw capture branch where it's missing.

- **A changed transform script** (`nifi/scripts/`): run
  `python provision/horus.py update-scripts` to see which flows differ, then
  `update-scripts --yes` to update them. Each ExecuteScript processor is stopped,
  given the new script and started again; its state (hormuz.now's last
  positions) is kept.
- **Any other change to a flow:** delete its process group in NiFi first (stop
  it and empty its queues), then re-run `create --yes`.
- **Rows a script got wrong:** fix the script and push it with
  `update-scripts --yes` first, so new rows are right. Then rebuild the rows
  already written from the bronze table (the responses as received, kept 30
  days):

  ```bash
  python provision/horus.py rebuild-from-raw --flow nws --from 2026-11-18 --to 2026-11-19        # the plan
  python provision/horus.py rebuild-from-raw --flow nws --from 2026-11-18 --to 2026-11-19 --yes  # replace
  ```

  It reruns the flow's current script over its raw responses, with each
  response's received time as the clock, and replaces that flow's rows captured
  in those days. Only finished days (not today), and never earlier than the
  flow's first raw response. Rebuilt rows have `ingest_run_id`
  `rebuild-<flow>-<time>`. Flows: `usgs`, `firms`, `opensky`, `adsblol`,
  `aisstream`, `hormuznow`, `eonet`, `nws`. A small flow's day takes a minute;
  an aisstream day (about 4 M messages) takes hours, mostly staging through
  Trino. Run it in a session: it needs `java` (in the runtimes) and downloads
  two Groovy jars from Maven Central on first use (set `GROOVY_JARS_DIR` to a
  folder holding `groovy-4.0.24.jar` and `groovy-json-4.0.24.jar` where there
  is no internet).

## 7. Ranger policies (manual, once per instance)

The Flink job needs two policies in the Data Lake's Ranger, and the tile
server one. Create them in
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
| S3 (`cm_s3`) | the storage bucket, path `/data/horus/<instance>/tiles`, recursive | the workload user who owns the tile server Application | read | The tile server reads the imagery from the bucket, each byte range signed by RAZ as the Application's user ([services/tileserver/README.md](../services/tileserver/README.md)). Read only: imagery is added by an admin (below), never by the service. |

Both lake policies are on the whole `horus_<instance>` database, so they also
cover the bronze table `raw_responses`. Keep it that way: bronze is source data
with no marking columns, so only the workload user and `ssb` should read it.
Analysts, agents and the UI read `events` and, later, the ontology; never grant
them the database, only `events_iceberg` (burndown 17.7).

### Imagery files

The imagery tile files (PMTiles) live in the environment's storage bucket under
`data/horus/<instance>/tiles/`, never in the Workbench project. Copy them there
from the machine that has them, with the AWS CLI or, without an AWS identity
for the account, through a Workbench session with `hdfs dfs -put`
([imagery/BURNDOWN-IMAGERY.md](../imagery/BURNDOWN-IMAGERY.md), E2). Each file
also needs a table in
[services/tileserver/tilesets.toml](../services/tileserver/tilesets.toml) stating
its licence and marking ([docs/TILESETS.md](TILESETS.md)). Writing to that
prefix needs its own Ranger S3 write policy for whoever uploads.

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

### Detections job

`create --yes` also submits [ssb/04_detections.sql](../ssb/04_detections.sql)
as `horus_<instance>_detections`. It reads the events topic from the latest
offset (live traffic only) and writes one JSON alert per detection to
`horus-<instance>-alerts`:

| Alert | Fires when | Severity |
|---|---|---|
| `AIS_GAP` | A vessel underway (3 kn or more) is silent for 2 hours or more and reappears near where it vanished, so it stopped while dark inside AIS coverage. Vessels that leave coverage reappear far away and are not flagged. | MEDIUM |
| `LOITERING` | A vessel reporting "under way" stays within about 1.5 nm for 90 minutes or more, at 0.3–2 kn. Anchored, moored and fishing vessels are excluded. | LOW |
| `STS_ENCOUNTER` | Two vessels, both under 2 kn and not moored, are within 0.15 nm (about 280 m) of each other over the same hour. | MEDIUM |
| `SPEED_JUMP` | Consecutive positions imply more than 60 kn for a vessel or 1000 kn for an aircraft, over a real distance: a spoofed position or a shared MMSI or ICAO address. | MEDIUM |
| `SQUAWK_EMERGENCY` | An aircraft squawks 7500 (unlawful interference) or 7700 (emergency), both HIGH, or 7600 (radio failure), MEDIUM. | HIGH or MEDIUM |

Each alert has a stable `alert_id`. A condition that persists produces one
alert per 6-hour bucket, not one per report. Thresholds are in the SQL views;
after changing one, run `ssb/test/run_local.sh` (Docker) to replay the
synthetic cases, then stop the job in SSB and re-run `create --yes`.

Known false positives: there is no port database yet, so `STS_ENCOUNTER` can
fire for ships berthed side by side whose AIS status is not "moored".

To see alerts arriving, run `python tools/tail_alerts.py` in a Workbench
session (add `--follow` to keep watching). If the job fails on topic
authorization, the provisioner prints the Ranger Kafka policy to add.

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
| Tile server | `horus/services/tileserver/serve-tiles.py` | Horus Node 22 | `TILESERVER_PUBLIC_URL=https://<tiles>.<domain>/`: this Application's **own** URL, with a trailing slash. A wrong host breaks every glyph, sprite and tile URL in the style. `TILESET_DIR=s3a://<bucket>/data/horus/<instance>/tiles/,/home/cdsw/horus/services/tileserver`: the imagery from the bucket, the basemap from the project folder | `/styles/dark/style.json` loads, and every URL in it starts with the tile server's own host; `/registry.json` lists the basemap and every imagery file; the log has no `SKIP` or `DENIED` lines |
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

### How long entities stay on the live map

The feeds-gateway keeps the latest update for each entity and drops it once
nothing new has arrived for a while. Ages are measured from when the gateway
received the update, so lakehouse replay behaves the same as live data.
Optional variables on the feeds-gateway Application:

| Variable | Default | Applies to |
|---|---|---|
| `FLIGHT_TTL_SECONDS` | `1500` (25 min) | aircraft |
| `VESSEL_TTL_MOVING_SECONDS` | `1200` (20 min) | ships at or above `VESSEL_MOVING_KNOTS` |
| `VESSEL_TTL_STATIONARY_SECONDS` | `3600` (60 min) | ships at anchor or moored, or with no speed |
| `VESSEL_MOVING_KNOTS` | `1.0` | the threshold between the two |
| `FEED_TTL_SECONDS` | `3600` (60 min) | every other feed |

The UI draws positions older than 15 minutes faded and marks them STALE, and
every aircraft and vessel popup shows **LAST UPDATE**.

### LLM (Mistral)

The feeds-gateway serves every AI feature in Horus: the `/llm` page, Ask Horus
(GraphRAG) and pattern-of-life. Set these on the feeds-gateway Application:

| Variable | Value |
|---|---|
| `LLM_BASE_URL` | `https://api.mistral.ai/v1` (Mistral Studio) |
| `LLM_API_KEY` | a Mistral API key from Mistral Studio |
| `LLM_MODEL` | `mistral-large-4` (the default) |
| `LLM_REASONING_EFFORT` | optional: `low`, `medium` or `high` for Mistral Large 4 (it rejects `none`). A reasoning model thinks before its first word and the gateway doesn't show the thinking, so higher means a longer silent wait |
| `POL_REASONING_EFFORT` | optional, default `low`: the effort for Pattern of Life only, which writes up facts already gathered. Empty uses `LLM_REASONING_EFFORT` |

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
| Tile server log: `DENIED reading <id>`, or `SKIP store s3a://…: RazUnauthorizedException` | Ranger refused the tile server's read: the tiles policy in step 7 is missing, names another user, or its path lacks the leading `/`. Ranger → **Audits** → **Access** shows the denied user and path. |
| Tile server log: `SKIP store s3a://…: ConnectionError: No valid kerberos ticket` | The Application has no Kerberos ticket, so RAZ can't sign. Check the workload password is set for the user who owns the Application, and restart it. |
| Map is blank; `style.json` loads but glyph, sprite or tile requests go to a different host | The tile server's `TILESERVER_PUBLIC_URL` isn't its own URL. Fix it on the tile server Application and restart. |
