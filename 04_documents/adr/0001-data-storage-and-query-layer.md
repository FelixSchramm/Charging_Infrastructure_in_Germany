# ADR 0001 — Data storage and query layer

- **Status:** Proposed
- **Date:** 2026-08-01
- **Deciders:** @FelixSchramm
- **Supersedes:** the "data is committed into the repo" note in `README.md`
- **Implementation progress:** tracked in [architecture-status.md](../architecture-status.md) —
  update it there when a step lands

## Context

Two things changed at the same time.

**1. Update frequency.** Access to an official public BNetzA REST API has been granted
(confirmed by e-mail, including a technical specification). It exposes the charging-point
register **once per day** instead of the current monthly XLSX. The ingest workflow therefore
moves from 12 runs per year to 365.

**2. Scope.** Additional datasets are planned:

| Dataset | Rough size | Change pattern |
| --- | --- | --- |
| Charging points (BNetzA) | ~10-20 MB parquet | full replace, daily |
| Charging sessions (*Ladevorgänge*) | ~5 GB | append-only history |
| Truck charging infrastructure | small | full replace |
| Weather data | grows continuously | append-only |
| Municipality / district data (AGS, geometries) | small | rarely |
| EV stock (KBA) | ~14 KB | monthly |

The current setup commits the resulting parquet files directly into Git. Two consequences
follow from the changes above.

*Repository growth.* Parquet is already compressed, so Git cannot delta-compress successive
versions meaningfully. At ~12 MB per day the history grows by roughly 4-5 GB per year.
GitHub recommends keeping repositories under 1 GB and strongly recommends staying under 5 GB.
This affects every clone and every Streamlit Community Cloud checkout.

*Memory ceiling.* Streamlit Community Cloud provides approximately 1 GB of RAM per app.
A 5 GB dataset can never be loaded into the app process, regardless of where it is stored.
This — not storage cost — is the binding constraint of the whole system.

## Constraints

- The project must remain **free of running cost**. Paid tiers are out of scope, including
  cheap ones, as long as a free alternative with acceptable effort exists.
- Streamlit Community Cloud (free tier) remains the hosting platform.
- Ingest must stay inside GitHub Actions (free for public repositories).
- No provider preference, but the solution must integrate with a Python ingest script and a
  pandas/geopandas-based Streamlit app.

## Options considered

Free-tier conditions researched on 2026-08-01. **These change — re-verify before relying on them.**

| Option | Free tier | Verdict |
| --- | --- | --- |
| **Stay in Git** | No hard limit; ~1 GB recommended, ~5 GB soft cap | Rejected — 4-5 GB/year history growth; 100 MB per-file block makes the 5 GB dataset impossible |
| **Git LFS** | 1 GiB storage + 1 GiB bandwidth (legacy), 10 GiB each on the newer billing platform | Rejected — every version counts cumulatively against storage; exceeding the quota without a payment method blocks LFS for the rest of the period |
| **GitHub Releases** | Up to 1000 assets per release, each file < 2 GiB, **no limit on total release size or bandwidth** | Accepted as fallback / secondary — no S3 API, no globbing, no partition pruning |
| **Cloudflare R2** | 10 GB-month storage, 1M Class A ops, 10M Class B ops, **egress always free** | **Accepted** |
| **AWS S3** | Accounts created on/after 2025-07-15 get $100 (+up to $100) in credits for max. 6 months, then the account is closed | Rejected — no permanent free tier |
| **Google Cloud Storage** | 5 GB-months, 5,000 Class A, 50,000 Class B, 100 GB transfer — US regions only | Rejected — 5 GB quota exhausted by a single dataset; 50k reads too tight for DuckDB range requests |
| **Supabase Storage** | 1 GB file storage, 5 GB egress, projects paused after 7 days of inactivity | Rejected — size and pause behaviour both disqualify it |
| **Backblaze B2** | First 10 GB free, egress free up to 3x average monthly storage, then $0.01/GB | Rejected — not strictly free at our egress pattern; Class C transactions billed |
| **Hugging Face Hub** | Best-effort free public storage | Kept as optional mirror, not primary |
| **MotherDuck (Lite)** | 3 users, 10 GB storage, 10 Pulse compute hours/month | Rejected — on a public dashboard, visitors consume the compute hours |
| **Neon (Free)** | 0.5 GB storage, 100 CU-hours/month, autosuspend after 5 min | Rejected — too small; also the wrong workload shape (analytical, read-only, batch-updated) |

## Decision

**Cloudflare R2 as the storage backend, with a four-layer data model and DuckDB for drill-down
queries. A small manifest file stays in Git.**

1. **`raw/`** — untouched source dumps, date in the path. Read by the ingest job only.
2. **`curated/`** — target schema, typed, ZSTD, Hive-partitioned. Only the columns the
   dashboard actually needs (the "slim model layer").
3. **`serving/`** — pre-computed aggregates, tens of MB, exactly matching the dashboard views.
   This is the only layer the app loads fully into memory.
4. **`02_data/manifest.json`** (in Git) — data timestamp, row counts, content hash.

The app reads `serving/` directly (fast path) and issues filtered DuckDB queries against
`curated/` only for drill-down (slow path).

## Rationale

R2 is the only provider whose free tier survives all three cost drivers at once: storage
(10 GB covers the 5 GB dataset), operations (10M Class B reads per month), and egress (free).
Egress is the decisive one, because DuckDB reads remote parquet through HTTP range requests
and can generate a large number of small requests — one reported case produced roughly 150,000
requests for a single wide parquet file. On R2 that is free; on GCS or B2 it becomes the bill.

The manifest file in Git solves three problems with one artefact:

- **Redeploy trigger.** Once data leaves the repo, data commits no longer trigger a Streamlit
  redeploy. The manifest commit restores that. (Strictly speaking the TTL cache would suffice —
  worst-case staleness one hour — but the manifest makes invalidation deterministic.)
- **Cache key.** `@st.cache_data` can key on the manifest hash instead of only a TTL, so the
  cache is invalidated when the data actually changed.
- **Scheduled-workflow keepalive.** In public repositories, scheduled workflows are
  automatically disabled after 60 days without repository activity, and only commits reset the
  timer — releases and tags do not. Without the daily manifest commit, the cron job would
  silently stop after two months.

## Consequences

**Positive**

- Repository history growth drops from gigabytes to kilobytes per year.
- The 5 GB dataset becomes usable without ever loading it into the app process.
- Storage and query layer are portable: parquet on S3-compatible storage works unchanged if
  the app ever moves off Streamlit Community Cloud.
- Read and write credentials are separated: the workflow gets a write token, the app a
  read-only token.

**Negative**

- One additional account and provider dependency. R2 activation generally requires a payment
  method on file even within the free tier.
- Two new secrets to manage (GitHub Actions + Streamlit).
- DuckDB's S3 support is tested against AWS S3, MinIO, Google Cloud and lakeFS; R2 is expected
  to work but is not on the tested list. **This must be verified before committing to the
  drill-down path** (see `04_documents/open-questions.md`).
- Ingest becomes stateful: partitions must be written idempotently, or a re-run creates
  duplicates.

**Neutral / accepted risk**

- Streamlit's ~1 GB RAM remains the ceiling. If interactive analysis of the charging sessions
  becomes a core feature, the app hosting must move — the storage architecture does not.

## Deliberately not decided here

- Whether raw data is retained long-term. See open question OQ-2: if the source archive is
  rolling rather than complete, discarding raw data is irreversible.
- Polars vs. DuckDB for the transformation step. Both handle 5 GB out-of-core on a
  GitHub-hosted runner (public repos: 4 vCPU / 16 GiB RAM, ~14 GB disk, 6 h job timeout).
  Decide by measurement, not preference.
- Whether a database is needed at all. It is not, for this workload — unless user-generated
  writes or PostGIS-grade spatial queries appear. Revisit in a separate ADR if so.

## References

- Cloudflare R2 pricing: https://developers.cloudflare.com/r2/pricing
- GitHub — About releases: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- GitHub — Disabling and enabling a workflow: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
- DuckDB — HTTP(S) support: https://duckdb.org/docs/lts/core_extensions/httpfs/https
- DuckDB — S3 API support: https://duckdb.org/docs/current/core_extensions/httpfs/s3api
- Streamlit — Manage your app (sleep after 12 h): https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app
- Google Cloud Storage pricing: https://cloud.google.com/storage/pricing
