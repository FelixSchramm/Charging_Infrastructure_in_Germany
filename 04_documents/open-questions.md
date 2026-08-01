# Open questions

Blocking items for [ADR 0001](adr/0001-data-storage-and-query-layer.md). Each of these should
also exist as a GitHub issue — the text below is ready to paste.

---

## OQ-1 — Measure the BNetzA REST API response

**Why it blocks:** every sizing decision in the ADR rests on an estimate. The response size,
record count and column width determine whether the slim model layer is 200 MB or 2 GB, and
whether the free tiers hold.

**Done when:**
- [ ] `measure_sources.yml` has been run against the real endpoint
- [ ] response size, record count, flattened column list recorded
- [ ] parquet size measured for the full column set and for the dashboard-only subset
- [ ] numbers written into `04_documents/data-model.md`

**Label:** `research`

---

## OQ-2 — Is the charging-session source archive complete or rolling?

**Why it blocks:** this is the only decision in the whole architecture that cannot be corrected
later. If the source only exposes a rolling window, or overwrites past values, then any day not
stored as raw data is permanently lost. If the archive is stable and fully re-downloadable, raw
retention becomes optional and the pipeline gets much simpler.

**Done when:**
- [ ] clarified **with the data provider**, not inferred from API behaviour
- [ ] answer documented here with date and contact
- [ ] retention decision recorded in the ADR ("Deliberately not decided here" section resolved)

Regardless of the answer: freeze one complete raw snapshot now. It costs 5 GB once and insures
against the source restricting its archive later.

**Label:** `research`, `blocked`

---

## OQ-3 — Verify DuckDB httpfs against Cloudflare R2

**Why it blocks:** the drill-down path depends on it. DuckDB's S3 support is tested against
AWS S3, MinIO, Google Cloud and lakeFS; R2 "should also work, but not all features may be
supported". If globbing or partition pruning misbehaves, the architecture still works — but
only via the fast path, and that changes what the dashboard can offer.

**Done when:**
- [ ] R2 bucket created, read-only token issued
- [ ] `INSTALL httpfs; LOAD httpfs;` + `read_parquet('s3://…/year=*/month=*/*.parquet')`
      verified against a partitioned test dataset
- [ ] confirmed that partition pruning actually reduces the scan (`EXPLAIN ANALYZE`)
- [ ] Class B operation count per typical query recorded (watch request amplification)

**Label:** `research`, `spike`

---

## OQ-4 — Polars or DuckDB for the transformation step?

**Why it matters:** both handle 5 GB out-of-core on a GitHub-hosted runner (public repos:
4 vCPU / 16 GiB RAM, ~14 GB disk, 6 h job timeout). The criterion is which one completes the
real transformation with less peak memory and less code — not preference.

**Done when:**
- [ ] both run against the real session dataset
- [ ] peak RSS and wall time recorded for each
- [ ] decision noted in the ADR

Likely outcome: Polars for the transformation, DuckDB for query-time. Not a blocker for
starting.

**Label:** `research`

---

## OQ-5 — Cloudflare account and payment method

**Why it matters:** R2 activation generally requires a payment method on file even inside the
free tier. In an institutional context this can be the slower path — worth starting early
rather than discovering it at implementation time.

**Done when:**
- [ ] account exists, R2 enabled
- [ ] bucket created, write token in GitHub Actions secrets, read token in Streamlit secrets
- [ ] billing alert configured

**Label:** `infrastructure`

---

## Not blocking, but worth tracking

- **OQ-6** — Replace the tech-debt note in `README.md` once the new path is live.
- **OQ-7** — Decide the lifecycle rule for `raw/` (proposed: delete snapshots older than
  90 days) before R2 usage approaches 10 GB.
- **OQ-8** — Re-verify all free-tier conditions in the ADR; they were researched on
  2026-08-01 and providers change them.
