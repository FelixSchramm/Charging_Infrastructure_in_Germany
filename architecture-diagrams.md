# Architecture diagrams (Mermaid)

Two diagrams at different levels of detail. Paste diagram 1 into `README.md`, diagram 2 into
`04_documents/architecture.md` (replacing the ASCII block).

GitHub renders these natively — no build step, no committed image. Preview them at
<https://mermaid.live> before pushing.

---

## 1 — README overview

Place this directly under the project description, above "Data Used".

Suggested intro line:

> Data is ingested daily by GitHub Actions, stored as partitioned parquet on Cloudflare R2,
> and served to the dashboard as pre-computed aggregates. Details:
> [architecture](04_documents/architecture.md) · [ADR 0001](04_documents/adr/0001-data-storage-and-query-layer.md)

```mermaid
flowchart LR
    subgraph SRC["Sources"]
        direction TB
        S1["BNetzA API<br/>charging points, daily"]
        S2["Charging sessions<br/>~5 GB, append-only"]
        S3["Weather, municipalities, EV stock"]
    end

    subgraph ETL["GitHub Actions"]
        direction TB
        T1["fetch"]
        T2["transform<br/>DuckDB / Polars"]
        T3["aggregate"]
        T1 --> T2 --> T3
    end

    subgraph STORE["Cloudflare R2"]
        direction TB
        L1["raw/<br/>archive"]
        L2["curated/<br/>partitioned parquet"]
        L3["serving/<br/>aggregates, tens of MB"]
    end

    subgraph APP["Streamlit Community Cloud"]
        direction TB
        A1["Dashboard"]
        A2["DuckDB in-process"]
    end

    SRC --> T1
    T1 --> L1
    L1 -. backfill .-> T2
    T2 --> L2
    T3 --> L3
    L3 --> A1
    L2 -. "drill-down via range requests" .-> A2
    A2 --> A1

    ETL --> MF["manifest.json<br/>in this repo"]
    MF -. "redeploy + cache key" .-> A1

    classDef store fill:#e8f1fb,stroke:#4a7fb5,color:#123
    classDef app fill:#eaf6ec,stroke:#5a9c67,color:#123
    classDef ctrl fill:#fdf3e3,stroke:#c9973f,color:#123
    class L1,L2,L3 store
    class A1,A2 app
    class MF ctrl
```

---

## 2 — Detailed data flow

For `04_documents/architecture.md`. Same system, one level deeper: shows write patterns and
partition keys, which is where most of the actual design lives.

```mermaid
flowchart TB
    subgraph SOURCES["External sources"]
        direction LR
        BN["BNetzA REST API<br/>daily"]
        SE["Charging sessions<br/>daily delta"]
        TR["Truck charging<br/>infrastructure"]
        WE["DWD weather<br/>daily"]
        MU["BKG municipalities<br/>on change"]
        KB["KBA EV stock<br/>monthly"]
    end

    subgraph JOBS["GitHub Actions, one workflow per cadence"]
        direction LR
        WD["update_daily"]
        WM["update_monthly"]
        WR["update_reference"]
    end

    BN --> WD
    SE --> WD
    TR --> WD
    WE --> WD
    KB --> WM
    MU --> WR

    subgraph RAW["raw/ — archive, ingest only"]
        R1["bnetza/date=.../"]
        R2["sessions/date=.../"]
    end

    subgraph CUR["curated/ — slim model layer"]
        C1["charging_points<br/>snapshot_date=<br/>FULL REPLACE"]
        C2["sessions<br/>year=/month=<br/>APPEND ONLY"]
        C3["weather<br/>year=/month=<br/>APPEND ONLY"]
        C4["municipalities<br/>valid_from=<br/>SLOWLY CHANGING"]
    end

    subgraph SRV["serving/ — dashboard shaped"]
        V1["kpi_municipality_month"]
        V2["geometries_simplified"]
    end

    JOBS --> RAW
    RAW -. "replay on schema change or bugfix" .-> JOBS
    JOBS --> CUR
    CUR --> SRV

    subgraph DASH["Streamlit app, ~1 GB RAM"]
        F["FAST PATH<br/>load serving/ fully"]
        S["SLOW PATH<br/>DuckDB httpfs,<br/>partition pruning"]
    end

    SRV --> F
    C2 -. "filtered query" .-> S

    JOBS --> MAN["02_data/manifest.json<br/>timestamp, row counts, hash"]
    MAN -. "triggers redeploy,<br/>keys the cache,<br/>keeps cron alive" .-> DASH

    classDef raw fill:#f4f4f4,stroke:#999,color:#123
    classDef cur fill:#e8f1fb,stroke:#4a7fb5,color:#123
    classDef srv fill:#dceafb,stroke:#31629c,color:#123
    classDef ctrl fill:#fdf3e3,stroke:#c9973f,color:#123
    class R1,R2 raw
    class C1,C2,C3,C4 cur
    class V1,V2 srv
    class MAN ctrl
```

---

## Notes

- **Keep the ASCII version as a fallback** in `04_documents/architecture.md`, wrapped in a
  collapsed `<details>` block. Mermaid renders on github.com, but not in every Markdown viewer,
  and not in exports to Word or PDF.
- **Add a text description** next to each diagram. Mermaid output is not accessible to screen
  readers, and a one-paragraph summary is what most readers actually read anyway.
- **`direction TB` inside subgraphs** is what keeps a left-to-right flowchart from becoming
  unreadably wide. If a diagram still overflows, split it rather than shrinking it.
- **Node count discipline.** If the README diagram grows past ~15 nodes, the detail belongs in
  diagram 2, not in the README.
- Colours use `classDef` rather than inline styles so they can be changed in one place. They
  are chosen to stay legible in both GitHub's light and dark themes.
