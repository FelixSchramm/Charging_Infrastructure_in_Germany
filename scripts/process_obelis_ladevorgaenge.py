"""Aggregiert die OBELIS-Ladevorgangsdaten zu Tageskennzahlen je Ladepunkt.

Die Rohdatei (~5 GB, halbjährlich von NOW GmbH veröffentlicht, kein stabiler
Direct-Link) wird manuell in ``02_data/01_original_data/`` abgelegt. DuckDB
aggregiert direkt auf der CSV, ohne die Datei komplett in den Speicher zu laden.

Die Aggregationslogik folgt der Deutschlandnetz-Auslastungs-SQL (Session ->
Tageswert je Ladepunkt): Plausibilitätsfilter, Summen und Mittelwerte je
Ladepunkt-Tag, Belegzeit im Fenster 06:00-22:00 mit Clipping sowie die
Auslastung in Prozent (Ganztag über 86400 s, Fenster über 57600 s).

Zeitzone: die OBELIS-Zeitstempel werden als bereits lokale (naive) deutsche Zeit
behandelt, daher keine zusätzliche AT-TIME-ZONE-Umrechnung wie in der SQL auf
timestamptz-Quellen. Sollten die Rohdaten in UTC vorliegen, müsste ``beginn``/
``ende`` vor dem ``CAST(... AS DATE)`` erst nach ``Europe/Berlin`` konvertiert
werden.

Ausführen: uv run python scripts/process_obelis_ladevorgaenge.py
"""

from pathlib import Path

import duckdb

RAW_DATA_DIR = Path("02_data/01_original_data")
OUT_PATH = Path("02_data/03_computed_data/obelis_ladevorgaenge_tagesdurchschnitt.parquet")

# Plausibilitätsgrenzen: die Rohdaten enthalten laut Metadaten Ausreißer
# (u.a. Zeitstempel zwischen 1809 und 2414, negative Energiewerte).
MIN_BEGINN = "2015-01-01"
MAX_DAUER_SEKUNDEN = 24 * 60 * 60
MAX_ENERGIE_WH = 300_000
MAX_LADELEISTUNG_KW = 1000

# Tagesfenster für die Auslastungsberechnung (analog zur Deutschlandnetz-SQL).
FENSTER_START_STUNDE = 6
FENSTER_ENDE_STUNDE = 22
SEKUNDEN_GANZTAG = 24 * 60 * 60  # 86400
SEKUNDEN_FENSTER_0622 = (FENSTER_ENDE_STUNDE - FENSTER_START_STUNDE) * 60 * 60  # 57600


def find_raw_file() -> Path:
    """Sucht die Rohdatendatei in RAW_DATA_DIR anhand des Namensmusters.

    :return: Pfad zur einzigen gefundenen Rohdatei.
    """
    matches = sorted(RAW_DATA_DIR.glob("*[Ll]adevorgaenge*.csv*")) + sorted(
        RAW_DATA_DIR.glob("*[Ll]adevorgaenge*.zip")
    )
    if not matches:
        raise FileNotFoundError(
            f"Keine Ladevorgänge-Rohdatei in {RAW_DATA_DIR} gefunden. "
            "Bitte die von OBELIS heruntergeladene Datei dort ablegen."
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"Mehrere mögliche Rohdateien gefunden: {matches}. "
            f"Bitte nur eine Datei in {RAW_DATA_DIR} belassen."
        )
    return matches[0]


def aggregate(raw_file: Path) -> duckdb.DuckDBPyRelation:
    """Aggregiert die Ladevorgänge je Ladepunkt und Tag.

    Die CTE ``sessions_clean`` filtert Ausreißer und berechnet je Session die
    ins Fenster 06:00-22:00 fallende Belegzeit. Das äußere SELECT bildet daraus
    Summen, Mittelwerte und Auslastungsquoten je ``lp_id``/Tag.

    :param raw_file: Pfad zur OBELIS-Rohdatei (CSV, ggf. gepackt).
    :return: DuckDB-Relation mit dem Tagesaggregat.
    """
    con = duckdb.connect()
    query = f"""
        WITH sessions_clean AS (
            SELECT
                lp_id,
                bundesland,
                lage,
                dauer_sekunden,
                energie_wh,
                maxladeleistunginkilowatt,
                CAST(beginn AS DATE) AS tag,
                -- Belegzeit pro Session, geclippt auf das Fenster 06:00-22:00
                -- des Starttages. LEAST(ende, 22:00) - GREATEST(beginn, 06:00)
                -- bildet die Schnittmenge mit dem Fenster; GREATEST(0, ...)
                -- verhindert negative Werte bei Sessions außerhalb des Fensters.
                GREATEST(
                    0,
                    EXTRACT(
                        EPOCH FROM
                        LEAST(
                            ende,
                            CAST(beginn AS DATE)
                            + INTERVAL '{FENSTER_ENDE_STUNDE} hours'
                        )
                        - GREATEST(
                            beginn,
                            CAST(beginn AS DATE)
                            + INTERVAL '{FENSTER_START_STUNDE} hours'
                        )
                    )
                ) AS belegzeit_0622_sek
            FROM read_csv_auto(?, union_by_name=true)
            WHERE beginn >= TIMESTAMP '{MIN_BEGINN}'
              AND beginn <= current_timestamp
              AND dauer_sekunden > 0
              AND dauer_sekunden < {MAX_DAUER_SEKUNDEN}
              AND energie_wh >= 0
              AND energie_wh < {MAX_ENERGIE_WH}
              AND maxladeleistunginkilowatt > 0
              AND maxladeleistunginkilowatt < {MAX_LADELEISTUNG_KW}
        )
        SELECT
            lp_id,
            tag,
            any_value(bundesland) AS bundesland,
            any_value(lage) AS lage,
            count(*) AS anzahl_ladevorgaenge,
            -- Summen (energie_wh -> kWh, OBELIS liefert durchgängig Wh)
            sum(energie_wh) / 1000.0 AS summe_energie_kwh,
            sum(dauer_sekunden) AS summe_dauer_sek,
            sum(dauer_sekunden) / 3600.0 AS summe_dauer_std,
            sum(dauer_sekunden) / 60.0 AS summe_dauer_min,
            sum(belegzeit_0622_sek) AS summe_belegzeit_0622_sek,
            -- Mittelwerte je Ladevorgang
            avg(energie_wh) / 1000.0 AS mean_energie_kwh_pro_lv,
            avg(dauer_sekunden) AS mean_dauer_sek_pro_lv,
            avg(dauer_sekunden) / 60.0 AS mean_dauer_min_pro_lv,
            avg(maxladeleistunginkilowatt) AS mean_ladeleistung_kw,
            -- Auslastung: belegte Zeit relativ zum Tages- bzw. Fensterbudget
            sum(dauer_sekunden) / {SEKUNDEN_GANZTAG}.0 * 100
                AS auslastung_ganztag_prozent,
            sum(belegzeit_0622_sek) / {SEKUNDEN_FENSTER_0622}.0 * 100
                AS auslastung_0622_prozent
        FROM sessions_clean
        GROUP BY lp_id, tag
    """
    return con.execute(query, [str(raw_file)])


def main():
    """Sucht die Rohdatei, aggregiert und schreibt das Ergebnis-Parquet."""
    raw_file = find_raw_file()
    print(f"Verarbeite: {raw_file}")

    result = aggregate(raw_file)
    df = result.fetch_df()
    print(f"  -> {len(df)} Ladepunkt-Tage nach Aggregation und Ausreißerfilter")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Gespeichert: {OUT_PATH} ({OUT_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
