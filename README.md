# Public Charging Infrastructure in Germany: Data Analysis & Dashboard

This project is an interactive dashboard application that visualizes the current state of public charging infrastructure in Germany. It was developed as a take-home task for a data analyst position at NOW GmbH.

🔗 **Link to the live application:** [https://ladeinfrastruktur-in-deutschland.streamlit.app/](https://ladeinfrastruktur-in-deutschland.streamlit.app/)

## Data Used

This project utilizes three main datasets:

1.  **Charging Infrastructure Data:** The Federal Network Agency's (BNetzA) public charging station register (*Ladesäulenregister*). The automated pipeline downloads the current XLSX directly from the [BNetzA download page](https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/DownloadundKontakt.html) and transforms it into one row per charging point (coordinates, operator, address, charging power, connector types). The original take-home version used the `ladestationFactTable.csv` / `ladepunktFactTable.csv` exports from the Mobilithek platform ([offer 842113170303512576](https://mobilithek.info/offers/842113170303512576)), which are still kept in `02_data/01_original_data/`.

2.  **EV Stock Data (KBA):** Electric-vehicle stock figures from the Federal Motor Transport Authority (Kraftfahrt-Bundesamt, KBA), used to relate charging infrastructure to the number of registered EVs.

3.  **Geospatial Data:** A Shapefile (`VG250_KRS.shp`) from the Federal Agency for Cartography and Geodesy (BKG). This data was used to visualize the German district boundaries and spatially join the charging infrastructure data for a map-based analysis.

## What Was Done

1.  **Data Integration:** The provided CSV files were processed and merged using Python and Pandas, joining them on a common `ladestation_id`.
2.  **Geospatial Join:** The aggregated charging infrastructure data was joined with the district boundary data to enable a visual representation of charging station density on a map.
3.  **Dashboard Development:** An interactive dashboard was built using Streamlit and Plotly. It allows users to visualize the charging infrastructure at the district level and apply filters (e.g., by state or charging type).

## Project Structure

The project follows a clear and professional folder structure for organization and reproducibility:
```
├── 01_app/
│   ├── app.py                     # Entry point (orchestrates the sections)
│   ├── config.py                  # Page config, colours, constants
│   ├── data_loading.py            # Cached data loaders
│   ├── filters.py                 # Sidebar filters + application
│   ├── sections/                  # One module per dashboard section
│   └── _data_version.py           # LAST_UPDATED stamp, bumped by the CI workflows
├── 02_data/
│   ├── 01_original_data/          # Original take-home CSVs from the charging register
│   │   ├── ladestationFactTable.csv
│   │   └── ladepunktFactTable.csv
│   ├── 02_meta_data/              # Geospatial data and other metadata (VG250_KRS Shapefile)
│   └── 03_computed_data/          # Processed parquet files read by the app
│       ├── combined_ladestation_ladepunkt.parquet
│       └── kba_ev_bestand.parquet
├── scripts/
│   ├── update_data.py             # Downloads BNetzA XLSX, writes the charging parquet
│   └── update_kba_data.py         # Updates the KBA EV-stock parquet
├── 03_notebooks/                  # Optional: For initial data analysis and prototyping
├── 04_documents/                  # Optional: For documentation or reports
├── .github/workflows/             # GitHub Actions data-update pipelines
├── .gitignore                     # Git configuration to ignore unwanted files
├── README.md                      # This file
├── pyproject.toml                 # Project metadata and dependencies (managed by uv)
├── uv.lock                        # Locked dependency versions
└── .streamlit/
    └── config.toml                # Streamlit configuration for app layout
```

## Automated Data Pipeline

The data is automatically updated on the **1st of every month** via a GitHub Actions workflow.

The pipeline ([`.github/workflows/update_data.yml`](.github/workflows/update_data.yml)) runs [`scripts/update_data.py`](scripts/update_data.py) and performs the following steps:

1. Scrapes the [BNetzA download page](https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/DownloadundKontakt.html) to find the current XLSX link
2. Downloads the latest charging station register (~26 MB)
3. Transforms the wide format (up to 6 connectors per row) into one row per charging point
4. Assigns district codes (AGS) via a spatial join with the shapefile
5. Saves the result as `combined_ladestation_ladepunkt.parquet` and commits it to the repository

The workflow can also be triggered manually via **GitHub Actions → Run workflow**.

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
> The target design is in [`ARCHITECTURE.md`](ARCHITECTURE.md),
> the per-dataset rules in [`04_documents/data-model.md`](04_documents/data-model.md).
>
> **Not yet implemented.** Three things are being measured first — real API response size, the
> retention question on the session data, and DuckDB/R2 compatibility — see
> [`04_documents/open-questions.md`](04_documents/open-questions.md). Until then the pipeline
> keeps working as described above.

## How to Run the Project

This project uses [**uv**](https://docs.astral.sh/uv/) for dependency management (Python >= 3.12). To run the dashboard locally:

1.  **Clone the repository:**
    `git clone https://github.com/YourUsername/Charging_Infrastructure_in_Germany.git`
    `cd Charging_Infrastructure_in_Germany`

2.  **Install dependencies** (uv creates the `.venv/` automatically from `pyproject.toml` / `uv.lock`):
    `uv sync`

3.  **Start the dashboard:**
    `uv run streamlit run 01_app/app.py`
