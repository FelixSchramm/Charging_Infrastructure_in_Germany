# OBELIS Ladevorgänge (Nutzungsdaten) ins Dashboard integrieren

## Quelle
- Mobilithek-Angebot: https://mobilithek.info/offers/714073450865197056
- Metadaten (bereits geladen und geprüft): https://d1269bxe5ubfat.cloudfront.net/obelisoe/metaData/OBELISoeffentlich_ladevorgaenge_Metadaten.xlsx
- Rohdaten: ~5 GB, kein stabiler Direct-Link auffindbar -> Nutzer lädt manuell herunter und
  legt die Datei in `02_data/01_original_data/` ab (Ordner ist bereits vollständig
  gitignored, also unkritisch für Repo-Größe).
- Update-Rhythmus: halbjährlich (Halbjahresberichte), kein Auto-Download möglich ->
  **kein GitHub-Actions-Workflow**, stattdessen lokales Skript, das der Nutzer nach
  jedem manuellen Download einmal ausführt.

## Rohdaten-Schema (aus Metadaten-xlsx)
| Spalte | Typ | Hinweise |
|---|---|---|
| lv_id | int | eindeutige Ladevorgangs-ID |
| beginn | datetime | Start; enthält Ausreißer (Jahre 1809–2414) und fehlende Werte |
| ende | datetime | Ende; Ausreißer + fehlende Werte |
| dauer_sekunden | double | Ausreißer |
| energie_wh | double | Ausreißer (negative + extreme Werte) |
| lp_id | varchar | Ladepunkt-ID, pro Datei zufällig gemischt (`_shuffled`) -> **nicht** mit dem BNetzA-Register joinbar |
| ls_id | varchar | Ladestation-ID, ebenfalls gemischt |
| bundesland | varchar | 16 Bundesländer, keine fehlenden Werte |
| lage | varchar | Standorttyp (Kundenparkplatz, Park & Ride, Parkhaus, Sonstige, Sonstige Tankstelle, Autobahn-Tankstelle, Öffentlicher Parkplatz); enthält fehlende Werte |
| maxladeleistunginkilowatt | double | Ausreißer |

## Verarbeitungsskript: `scripts/process_obelis_ladevorgaenge.py`
- Neue Dependency: `duckdb` (out-of-core SQL-Aggregation direkt auf der CSV, kein
  Laden von 5 GB in den pandas-Speicher nötig).
- Ablauf:
  1. Rohdatei per Glob in `02_data/01_original_data/` suchen (Muster `*ladevorgaenge*`,
     akzeptiert `.csv`, `.csv.gz`, `.zip`); Fehler mit klarer Meldung, falls 0 oder >1 Treffer.
  2. Plausibilitätsfilter vor der Aggregation (Grenzwerte als Konstanten oben im Skript):
     - `beginn` zwischen 2015-01-01 und heute
     - `dauer_sekunden` > 0 und < 24h in Sekunden (Ladevorgänge über einen Tag sind unplausibel)
     - `energie_wh` >= 0 und < 300 000 (entspricht 300 kWh, deutlich über realistischer Tagesladung)
     - `maxladeleistunginkilowatt` > 0 und < 1000
  3. Aggregation via DuckDB `GROUP BY lp_id, CAST(beginn AS DATE)` — Logik analog zur
     Deutschlandnetz-Auslastungs-SQL (Session -> Tageswert je Ladepunkt):
     - `anzahl_ladevorgaenge` (count)
     - Summen: `summe_energie_kwh` (energie_wh/1000, OBELIS liefert durchgängig Wh),
       `summe_dauer_sek` / `summe_dauer_std` / `summe_dauer_min`,
       `summe_belegzeit_0622_sek`
     - Mittelwerte: `mean_energie_kwh_pro_lv`, `mean_dauer_sek_pro_lv`,
       `mean_dauer_min_pro_lv`, `mean_ladeleistung_kw`
     - Auslastung: `auslastung_ganztag_prozent` (summe_dauer_sek / 86 400 * 100),
       `auslastung_0622_prozent` (summe_belegzeit_0622_sek / 57 600 * 100)
     - Belegzeitfenster 06:00-22:00 je Session per Clipping
       `GREATEST(0, LEAST(ende, tag+22h) - GREATEST(beginn, tag+6h))`
     - `bundesland`, `lage` (any_value, da pro lp_id konstant)
  4. Ergebnis als `02_data/03_computed_data/obelis_ladevorgaenge_tagesdurchschnitt.parquet`
     schreiben (kompakt, committable).

### Bewusst NICHT aus der Deutschlandnetz-SQL übernommen (datensatzspezifisch)
- **date_spine + Zero-Filling + 90-Tage-Reifefilter + fester Zeitraum**: Rollout-Logik
  des Deutschlandnetzes; für OBELIS (bundesweit, halbjährlich, sehr viele `lp_id`) ohne
  fachliche Entsprechung und Parquet-sprengend.
- **Kosten (`total_cost`), `max_power` je Ladepunkt, `evse_id`**: in OBELIS nicht vorhanden.
- **AT-TIME-ZONE-Umrechnung**: OBELIS-Zeitstempel werden als bereits lokale deutsche Zeit
  behandelt (naive Timestamps). Falls die Rohdaten in UTC vorliegen, müsste vor
  `CAST(... AS DATE)` nach `Europe/Berlin` konvertiert werden (im Skript dokumentiert).
- Ausführung: `uv run python scripts/process_obelis_ladevorgaenge.py`, manuell nach
  jedem halbjährlichen Datenexport; Ergebnis-Parquet wird wie die anderen
  computed-data-Dateien committet.

## Dashboard-Integration
- `01_app/data_loading.py`: `load_obelis_usage()` (`@st.cache_data(ttl=3600)`),
  liest das neue Parquet, gibt `None` zurück, falls die Datei (noch) fehlt
  (Analog zu `load_kba_data()`).
- Neuer Abschnitt `01_app/sections/usage.py` (`render_usage`):
  - KPIs: Anzahl Ladevorgänge, Energiemenge (kWh) gesamt, Ø Dauer, Ø Ladeleistung
  - Zeitverlauf: Ladevorgänge/Energie pro Monat
  - Balkendiagramm: Ladevorgänge nach `lage` (Standorttyp)
  - Balkendiagramm: Energie nach Bundesland
  - Filter: nur `filters.bundeslaender` anwendbar (einzige gemeinsame Dimension
    mit dem Haupt-Filter-State; `leistungstypen`/Jahre/Suche greifen nicht, da
    andere Datenbasis)
  - Fallback: `st.info(...)`, wenn `df_usage is None` (Parquet noch nicht generiert)
- `01_app/app.py`: neuer Tab **"Nutzung"** (nach "Analysen", vor "Landkreise")
- `01_app/sections/__init__.py`: `render_usage` exportieren

## Offene Punkte / Hinweise an den Nutzer
- lp_id/ls_id sind pro Export neu gemischt -> Nutzungsdaten können **nicht**
  auf Ladepunkt-/Stationsebene mit dem BNetzA-Register verknüpft werden.
  Gemeinsame Dimension ist nur `bundesland`.
- Aggregat-Parquet muss nach jedem neuen OBELIS-Export manuell neu erzeugt und
  committet werden (kein CI-Automatismus, da kein stabiler Download-Link).
