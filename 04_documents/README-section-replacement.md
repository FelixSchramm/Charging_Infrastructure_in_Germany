# README replacement

Replace the blockquote under **Automated Data Pipeline** that currently begins
`> **Note — data is committed into the repo (tech-debt to revisit).**` with the text below.

The existing note documents "data in Git" as a deliberate choice justified by small files and
infrequent updates. Both premises are gone: the BNetzA source moves to daily, and additional
datasets of a different order of magnitude are planned. Leaving the old note in place means the
repository documents an architecture the project is actively leaving.

---

## Where the data lives

> **In transition.** The pipeline currently commits the resulting `.parquet` files directly
> into Git, which was a reasonable choice while updates were monthly and files were ~7 MB.
> With the move to a daily BNetzA REST API and additional datasets — including charging
> sessions in the multi-gigabyte range — that no longer holds: parquet does not delta-compress,
> so daily commits would add several GB of Git history per year, and a 5 GB dataset cannot be
> committed at all (GitHub blocks files over 100 MB).
>
> The target architecture moves the data to **Cloudflare R2**, with a layered model
> (`raw/` → `curated/` → `serving/`), pre-computed aggregates for the dashboard, and DuckDB
> over HTTP range requests for drill-down. A small `02_data/manifest.json` stays in Git as the
> control plane: it triggers the Streamlit redeploy, serves as the cache key, and keeps the
> scheduled workflow from being auto-disabled after 60 days of no commits.
>
> The reasoning, the alternatives considered (GitHub Releases, Git LFS, S3, GCS, Supabase,
> B2, MotherDuck, Neon) and their free-tier conditions are documented in
> [`04_documents/adr/0001-data-storage-and-query-layer.md`](04_documents/adr/0001-data-storage-and-query-layer.md).
> The target design is in [`04_documents/architecture.md`](04_documents/architecture.md),
> the per-dataset rules in [`04_documents/data-model.md`](04_documents/data-model.md).
>
> **Not yet implemented.** Three things are being measured first — real API response size, the
> retention question on the session data, and DuckDB/R2 compatibility — see
> [`04_documents/open-questions.md`](04_documents/open-questions.md). Until then the pipeline
> keeps working as described above.

---

## Also worth adjusting

- **`.gitignore`** — add `02_data/03_computed_data/*.parquet` **now**, but keep the existing
  files tracked (`git update-index` is not needed; the ignore rule only affects new files).
  They remain the production data source until the migration is complete.
- **Project structure section** — add the `04_documents/` contents once these files are in.
- **Clone URL** — the README currently shows
  `git clone https://github.com/YourUsername/Charging_Infrastructure_in_Germany.git`, which is
  neither the real user nor the real repo name. Small thing, but it breaks copy-paste.
- **`CLAUDE.md`** — worth adding a pointer to the ADR so that future AI-assisted changes start
  from the decided architecture rather than re-deriving it.
