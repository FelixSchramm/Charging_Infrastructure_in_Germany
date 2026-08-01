# Architecture

Target state for the data pipeline and dashboard. See
[ADR 0001](04_documents/adr/0001-data-storage-and-query-layer.md) for why these choices were made,
and [data-model.md](04_documents/data-model.md) for the per-dataset schema and partitioning rules.

**Status: target state, not yet implemented.** The current pipeline still commits parquet
files into the repository (see `README.md`).

## Overview

```
EXTERNAL SOURCES              INGEST (GitHub Actions)              STORAGE (Cloudflare R2)          APP (Streamlit Community Cloud)
────────────────────          ───────────────────────              ───────────────────────          ──────────────────────────────

BNetzA REST API   ──┐          ┌─────────────────────┐             ┌──────────────────────┐
  (daily)           │          │ 1  fetch            │────────────▶│ raw/                 │
                    │          │                     │             │   bnetza/<date>.json │
Charging sessions ──┤          │ 2  transform        │◀────────────│   sessions/…         │
  (append-only)     │          │    DuckDB / Polars  │  backfill   │   …                  │
                    │          │    out-of-core      │             ├──────────────────────┤
Truck charging    ──┼─────────▶│                     │────────────▶│ curated/             │
  infrastructure    │          │ 3  aggregate        │             │   charging_points/   │
                    │          │                     │             │   sessions/          │
Weather (DWD)     ──┤          │ 4  write serving    │────────────▶│     year=/month=     │
  (append-only)     │          │                     │             │   weather/year=/…    │
                    │          │ 5  write manifest   │             │   municipalities/    │
Municipalities /  ──┤          └─────────────────────┘             ├──────────────────────┤
  AGS + geometry    │                     │                        │ serving/             │
                    │                     │                        │   kpi_muni_month     │──▶ FAST PATH
EV stock (KBA)    ──┘                     │                        │   geometries_simpl   │    load fully (~10-30 MB)
  (monthly)                               │                        └──────────────────────┘
                                          │                                    ▲
                                          ▼                                    │
                            ┌──────────────────────────┐                       └──▶ SLOW PATH
                            │ GitHub repository        │                            DuckDB + httpfs,
                            │   01_app/       code     │                            range requests,
                            │   scripts/      ingest   │                            partition pruning
                            │   02_data/manifest.json  │                            against curated/
                            └──────────────────────────┘                                 │
                                          │                                              │
                                          ├──── redeploy on commit ─────────────────────▶│
                                          └──── manifest hash = cache key ──────────────▶│
```

Two arrows in this diagram are easy to omit and both matter:

- **`raw/` back into transform.** Raw data only has value if it can be replayed. Without that
  arrow, a bug found three months later cannot be fixed retroactively.
- **repository into app.** The app is deployed from this repo and currently learns about new
  data through data commits. Once the data leaves the repo, that link has to be re-established
  explicitly — otherwise the dashboard silently serves stale data and the cron job is disabled
  after 60 days.

Note also that **DuckDB is not a separate service.** It runs in-process inside the Streamlit
app and therefore shares the same ~1 GB memory budget as the dashboard itself.

## Storage layers

### `raw/` — archive

Untouched source responses with the retrieval date in the path. Read by the ingest job only,
never by the app. Purpose: reproducibility and replay after a transformation bug.

Charging sessions are stored as one frozen full snapshot plus daily deltas — the 5 GB are not
rewritten every day.

Lifecycle rule (once R2 usage approaches the 10 GB free tier): delete raw snapshots older than
90 days, since the curated layer supersedes them.

### `curated/` — slim model layer

Target schema, typed, ZSTD-compressed, Hive-partitioned. Contains **only the columns the
dashboard needs** — typically a small subset of the source columns. In practice this lands at
roughly 5-15 % of the raw size, which keeps re-aggregation possible without re-downloading the
source.

Write pattern depends on the dataset, not on convenience:

- full replace (charging points, truck infrastructure) — small, rewritten daily
- append-only (sessions, weather) — only the new partition is written
- slowly changing dimension (municipalities, KBA) — written only on change

Partition keys are chosen to match the dashboard's dominant filter, so that DuckDB can prune
whole partitions before issuing range requests.

### `serving/` — dashboard-shaped aggregates

A handful of pre-computed files in the low tens of MB, matching the dashboard views one to one
(e.g. KPIs per municipality/district/state and month, joined via AGS). Attribute data and
geometries are separate files; geometries are topology-preservingly simplified.

This is the only layer loaded fully into the app process. **Rule of thumb: nothing the app
loads completely may exceed a few tens of MB.** That rule is what keeps the app inside the
1 GB budget.

### `02_data/manifest.json` — control plane (in Git)

A few hundred bytes per day: data timestamp, per-dataset row counts, content hash. Triggers
the Streamlit redeploy, serves as the `@st.cache_data` key, and keeps the scheduled workflow
alive. This replaces the role currently played by `01_app/_data_version.py`.

## Daily sequence

1. Fetch sources (separate workflows per update frequency — daily, monthly, yearly; there is
   no point polling a yearly dataset every night).
2. Write raw responses to `raw/`.
3. One DuckDB (or Polars) session: read raw, write new `curated/` partitions, compute
   `serving/` files — streaming, nothing fully in memory.
4. Update and commit `02_data/manifest.json`.

**Every step must be idempotent.** A second run on the same day must overwrite the same
partitions without producing duplicates, otherwise every retry after a failure becomes a data
problem.

## Credentials

Deliberately asymmetric:

| Where | Token | Scope |
| --- | --- | --- |
| GitHub Actions secret | R2 API token | object read + write, scoped to the bucket |
| Streamlit secret | R2 API token | **read only** |

A leaked app secret cannot destroy data.

## Known limits and where this breaks

| Limit | Value | Mitigation |
| --- | --- | --- |
| R2 free storage | 10 GB-month | lifecycle rule on `raw/` |
| R2 free operations | 1M Class A / 10M Class B per month | large row groups, fewer/larger files |
| Streamlit memory | ~1 GB per app | keep `serving/` small; never load `curated/` fully |
| Streamlit sleep | after 12 h without traffic | accepted; cold start reloads from R2 |
| Actions job timeout | 6 h | out-of-core transformation, incremental partitions |
| Scheduled workflow | disabled after 60 days without commits | daily manifest commit |

If interactive analysis of the charging sessions becomes a core feature, the binding
constraint is the app's memory, not the storage. The migration path is then to move the app
hosting first (same code, small VPS, DuckDB file locally) — not to introduce a database.
