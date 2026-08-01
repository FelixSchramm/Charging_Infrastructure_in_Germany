# Architecture rollout status

Tracks implementation progress of the target architecture described in
[ARCHITECTURE.md](../ARCHITECTURE.md) and decided in
[ADR 0001](adr/0001-data-storage-and-query-layer.md). This is the single place to check
"how far are we" — and the single place to update when a step lands.

**Update this file whenever a step below is completed.** That is what keeps it authoritative.
Don't duplicate research results here — link to [open-questions.md](open-questions.md) instead.

- **Last updated:** 2026-08-01
- **Overall status:** Not started — target state only, nothing below is implemented yet.

## Definition of done

The architecture counts as implemented when all of these hold:

- [ ] Every dataset in [data-model.md](data-model.md) is written through the
      `raw/` → `curated/` → `serving/` pipeline on Cloudflare R2.
- [ ] The app loads `serving/` fully (fast path) and queries `curated/` via DuckDB httpfs for
      drill-down (slow path) — no dataset below is read from a parquet file committed to Git
      anymore.
- [ ] `02_data/manifest.json` drives the Streamlit redeploy and the `@st.cache_data` key.
- [ ] ADR 0001 status changed from "Proposed" to "Accepted".
- [ ] The "Status: target state, not yet implemented" line in ARCHITECTURE.md is removed.
- [ ] README.md's data-pipeline section reflects the new pipeline (OQ-6).

## Phase 0 — Blocking research

Detail, "done when" criteria and labels live in [open-questions.md](open-questions.md) — update
status there, mirror the checkbox here.

- [ ] OQ-1 — measure BNetzA REST API response size/shape
- [ ] OQ-2 — charging-session archive: complete or rolling?
- [ ] OQ-3 — DuckDB httpfs verified against R2
- [ ] OQ-4 — Polars vs. DuckDB for the transform step
- [ ] OQ-5 — Cloudflare account + payment method

## Phase 1 — Infrastructure

- [ ] R2 bucket created
- [ ] Write token issued, stored as GitHub Actions secret
- [ ] Read-only token issued, stored as Streamlit secret
- [ ] Billing alert configured (OQ-5)

## Phase 2 — Ingest pipeline, per dataset

A row counts as done once `raw/`, `curated/` and `serving/` are all written for that dataset and
the write pattern matches [data-model.md](data-model.md).

| Dataset | raw/ | curated/ | serving/ | Notes |
| --- | --- | --- | --- | --- |
| `charging_points` | [ ] | [ ] | [ ] | daily API integration currently tracked separately — see note below |
| `sessions` | [ ] | [ ] | [ ] | blocked on OQ-2 |
| `truck_charging` | [ ] | [ ] | [ ] | |
| `weather` | [ ] | [ ] | [ ] | |
| `municipalities` | [ ] | [ ] | [ ] | |
| `ev_stock` | [ ] | [ ] | [ ] | |

## Phase 3 — App changes

- [ ] App reads `serving/` from R2 (fast path)
- [ ] DuckDB httpfs slow path wired up for drill-down queries against `curated/`
- [ ] `@st.cache_data` keyed on manifest hash instead of TTL only
- [ ] Manifest commit triggers redeploy, verified end-to-end

## Phase 4 — Cutover & decommission

- [ ] Decision recorded: keep, freeze, or remove `scripts/update_data.py` /
      `scripts/update_kba_data.py` (the parquet-in-Git path)
- [ ] `.github/workflows/update_data.yml` / `update_kba_data.yml` updated or retired
- [ ] README.md data section rewritten (OQ-6)
- [ ] CLAUDE.md paths/conventions updated to match

## Phase 5 — Verification

- [ ] Idempotency verified: re-running the same day's ingest does not duplicate partitions
- [ ] Streamlit memory usage checked against the ~1 GB budget
- [ ] One month of R2 usage observed and compared against free-tier limits (OQ-8)

## Related, separate workstream

[plans/2026-06-26_offizielle-api-implementierung.md](../plans/2026-06-26_offizielle-api-implementierung.md)
integrates the daily BNetzA REST API but — as currently written — still writes to the *existing*
parquet-in-Git pipeline, not to R2. Treat it as a stepping stone: once it is live, its output
becomes the `fetch` step feeding the `charging_points` row in Phase 2 above, not a separate
finish line.
