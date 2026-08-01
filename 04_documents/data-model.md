# Data model

Per-dataset catalogue: source, cadence, write pattern, partitioning. This is the document that
prevents the 5 GB session dataset from being rewritten every night.

Fill in the `TODO` fields once the measurement run (`measure_sources.yml`) has produced real
numbers.

## Conventions

- **Format:** parquet, ZSTD compression, dictionary encoding for low-cardinality strings.
- **Target file size:** 128-256 MB per file. Many small files multiply HTTP requests and
  defeat DuckDB's range-request efficiency.
- **Partitioning:** Hive style (`key=value/`), chosen to match the dashboard's dominant filter.
- **Naming:** `snake_case`, English column names, ISO-8601 dates, `AGS` as the join key for
  everything spatial.
- **Timezone:** all timestamps stored as UTC; converted for display only.
- **Idempotency:** writes replace a whole partition, never append rows into an existing file.

## Datasets

### `charging_points` — BNetzA charging point register

| | |
| --- | --- |
| Source | BNetzA public REST API (spec received by e-mail). Previously: XLSX scraped from the BNetzA download page (~26 MB) |
| Cadence | daily |
| Write pattern | **full replace** |
| Partitioning | `snapshot_date=YYYY-MM-DD` (keep a rolling window; the app reads the latest) |
| Size | ~10-20 MB parquet expected — TODO: measure |
| Records | order of 100,000 charging facilities — TODO: confirm |
| Notes | Nested response (station → charging point → connector type); flatten to one row per charging point, as the current pipeline already does. AGS assigned via spatial join with VG250. |

### `sessions` — charging sessions (*Ladevorgänge*)

| | |
| --- | --- |
| Source | TODO |
| Cadence | TODO — daily delta expected |
| Write pattern | **append-only** — never rewrite history |
| Partitioning | `year=YYYY/month=MM` |
| Size | ~5 GB raw; TODO: measure slim-layer size after column selection |
| Notes | **The critical dataset.** Keep only the columns the dashboard needs — typically timestamp, duration, energy, charging-point ID, power — out of a much wider source. If the source revises past data, rewrite the affected month completely; parquet has no UPDATE. Blocked on OQ-2 (is the source archive complete or rolling?). |

### `truck_charging` — truck charging infrastructure

| | |
| --- | --- |
| Source | TODO |
| Cadence | TODO |
| Write pattern | full replace |
| Partitioning | `snapshot_date=YYYY-MM-DD` |
| Size | small |

### `weather` — DWD weather data

| | |
| --- | --- |
| Source | DWD Open Data |
| Cadence | daily |
| Write pattern | append-only |
| Partitioning | `year=YYYY/month=MM` |
| Notes | The only dataset that grows without bound. Curate to the resolution the dashboard actually shows (e.g. daily means per district, not hourly values per station) — decide this before the first import, not after. |

### `municipalities` — AGS, districts, geometries

| | |
| --- | --- |
| Source | BKG VG250 (`VG250_KRS.shp`), currently in `02_data/02_meta_data/` |
| Cadence | on territorial change (roughly yearly) |
| Write pattern | slowly changing dimension |
| Partitioning | `valid_from=YYYY-MM-DD` |
| Notes | **Second hidden memory risk after the sessions.** Unsimplified geometries expand to a multiple of their file size in a GeoDataFrame. Store simplified geometries (topology-preserving, e.g. mapshaper/topojson) as a separate serving file, split from the attribute data. |

### `ev_stock` — KBA electric vehicle stock

| | |
| --- | --- |
| Source | Kraftfahrt-Bundesamt |
| Cadence | monthly |
| Write pattern | append-only by reporting month |
| Partitioning | none needed (~14 KB) |
| Notes | Different cadence from the BNetzA data — belongs in its own workflow, not the daily one. Join key: AGS. |

## Serving artefacts

Derived from `curated/`, rebuilt on every ingest run.

| File | Content | Target size |
| --- | --- | --- |
| `kpi_municipality_month.parquet` | charging points, power, sessions, energy, EV stock per AGS and month | 10-30 MB |
| `geometries_simplified.parquet` | simplified district/municipality geometries, keyed by AGS | TODO |

Roughly 11,000 municipalities x 60 months x a handful of measures is a few hundred thousand
rows — comfortably inside the app's memory budget.

## Cadence summary

Three different update frequencies converge here. Splitting them into separate workflows avoids
pulling unchanged sources every night:

| Workflow | Datasets | Schedule |
| --- | --- | --- |
| `update_daily` | charging points, sessions, weather | daily |
| `update_monthly` | EV stock (KBA) | monthly |
| `update_reference` | municipalities / geometries | manual / on change |
