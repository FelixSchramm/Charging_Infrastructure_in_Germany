# Ausführplan: Offizielle BNetzA-Tages-API anbinden

> **Status (2026-08-01, aktualisiert):** Antwort von `ladesaeulenregister@bnetza.de`
> ist da, inkl. OpenAPI-Spec (lokal, nicht committed — siehe
> `.gitignore`-Eintrag "BNetzA_Liste der Ladesäulen*.yml"; Grund: privat
> zugeschickt, nicht als frei weiterverbreitbares Dokument gekennzeichnet,
> Rückfrage bei BNetzA dazu noch offen). Dieser Plan ist jetzt gegen die
> tatsächliche Spec verifiziert (nicht mehr nur Annahmen). Zwei der ursprünglich
> offenen Fragen (Granularität, Datumsformat) haben eine **andere** Antwort
> bekommen als die zwei Optionen, die ursprünglich zur Auswahl standen — siehe
> Abschnitt 2.

---

## 0. Warum überhaupt
- Bisher genutzter Endpoint `services2.arcgis.com/.../Ladesaeulen_in_Deutschland/
  FeatureServer/0` ist ein **monatlicher Snapshot** → hinkt der Realität hinterher.
- Die offizielle Schnittstelle wird laut BNetzA-Mail **"in der Regel einmal
  täglich aktualisiert"**.

## 1. Verifizierte API-Fakten (aus der OpenAPI-Spec, Version 1.0.2)

- **Endpoint:** `GET https://ladesaeulenregister.bnetza.de/els/service/public/v1/chargepoints`
  — **keine Query-Parameter** definiert (kein Offset/Limit/Cursor).
  → ein einzelner Request liefert vermutlich den kompletten Bestand als ein
  JSON/XML-Dokument. Vor dem produktiven Einsatz einmal live prüfen, wie groß
  die Antwort tatsächlich ist (MB) und ob es doch eine faktische Grenze gibt,
  die in der Spec nicht dokumentiert ist.
- **Auth:** kein `security:`-Block in der Spec → vermutlich kein Token nötig.
  Nicht zu 100 % belegt, nur die Abwesenheit einer Angabe — **einmal live
  testen**, bevor man sich darauf verlässt.
- **Format:** JSON oder XML (beides in der Spec vorgesehen) — JSON verwenden,
  passt zu `requests`/pandas ohne Zusatz-Parser.
- **Fehlerfälle laut Spec:**
  - `404` = "Der Export wurde noch nicht bereitgestellt" (kein Fehler im
    klassischen Sinn, aber auch keine Daten — Skript muss abbrechen, ohne die
    alte gute Datei zu überschreiben, s. Abschnitt 4).
  - `500` = serverseitiger Fehler.
- **Antwort-Hülle (`ExportResponse`):**
  ```json
  {
    "documentDate": "01.01.2025",
    "documentTime": "08:00 Uhr",
    "chargingStations": [ ... ]
  }
  ```
  `documentDate` ist der Datenstand → direkt für `_data_version.py` verwendbar
  (kein `date.today()`-Fallback nötig wie beim ArcGIS-Plan).
- **Struktur ist verschachtelt, nicht breit:** `chargingStations[].evses[].connectors[]`.
  BNetzA nennt `evses` in der Spec selbst **"Ladepunkte"** (`title: Ladepunkte`)
  — ein Evse = ein physischer Ladepunkt, kann aber **mehrere Connectors**
  (Stecker-Varianten) haben (Beispiel in der Spec: ein Evse mit Schuko **und**
  Typ-2-Steckdose gleichzeitig). Das ist wichtig für Abschnitt 3.

### Feld-Mapping (API → Ziel-Schema)

| API-Feld | Ziel-Spalte | Hinweis |
|---|---|---|
| `id` | — | BNetzA-interne Stations-ID, aktuell keine Zielspalte dafür |
| `operator.companyName` | `Betreiber` | Beispiel-Payload zeigt: `companyName` = voller Name, `displayName` = Kurzname — **Titel in der Spec sind vertauscht formuliert** ("Anzeigename" für `companyName`), am Beispiel orientiert, aber vor Produktivsetzung an echten Daten gegenchecken |
| `type` | `ArtLadeeinrichtung` | Enum: `Normalladeeinrichtung` / `Schnellladeeinrichtung` |
| `street` | `Strasse` | |
| `house_no` | `Hausnummer` | |
| `address_addition` | `Adresszusatz` | |
| `city` | `Ort` | |
| `postal_code` | `PLZ` | |
| `district_independent_city` | `KreisKreisfreieStadt` | |
| `state` | `Bundesland` | |
| `coordinates.latitude` | `Breitengrad` | bereits `number`/`double`, kein `_to_float`-String-Parsing nötig |
| `coordinates.longitude` | `Laengengrad` | s.o. |
| `go_live_date` | `Inbetriebnahmedatum` | **String `"dd.MM.yyyy"`**, z. B. `"01.01.2025"` — `pd.to_datetime(col, format="%d.%m.%Y")` |
| `max_electric_power_station` | `InstallierteLadeleistungNLL` / `NennleistungBNetzA` | Spec-Titel ist wörtlich "Nennleistung Ladeeinrichtung [kW]" — 1:1-Treffer |
| `len(evses)` (berechnet) | `AnzahlLadepunkteBNetzA` | **kein direktes Feld** — muss pro Station als Anzahl der Evses gezählt werden, s. Abschnitt 3 |
| `evses[].evse_id` | Basis für `ladepunkt_id` | s. Abschnitt 7 — löst die bisher offene Frage |
| `evses[].connectors[].connector_type` | `Steckertyp` | eigener Enum mit anderen Werten als die alte XLSX-Quelle — unkritisch, s. u. |
| `evses[].connectors[].max_electric_power_connector` | `LadeleistungInKW` | bereits `number`/`double` |

Nicht im Ziel-Schema, aber in der API vorhanden (ignorieren, keine Zielspalte):
`location_description`, `payment_systems`, `access_restriction`,
`opening_hours_specification`, `opening_days`, `public_key`/`public_key_available`.

**Steckertyp-Werte:** Der neue Enum (`AC Typ 2 Steckdose`, `DC CHAdeMO`, …) wird
vermutlich nicht wortgleich mit den bisherigen XLSX-Werten sein. Geprüft, ob
das irgendwo Filter-/Farblogik bricht: **nein** — `Leistungskategorie` (worauf
alle Filter/Diagramme basieren, `01_app/data_loading.py:33-51`) wird rein aus
der numerischen `LadeleistungInKW` abgeleitet. `Steckertyp` wird nur roh in der
Datentabelle angezeigt (`01_app/sections/data_table.py:24`). Andere Wortwahl
ist also kosmetisch, nicht funktional riskant.

---

## 2. Offene Punkte — jetzt beantwortet

1. ~~Endpoint-URL~~ → siehe Abschnitt 1.
2. ~~Auth~~ → vermutlich kein Token, unverifiziert (live testen).
3. ~~Format~~ → JSON.
4. ~~Pagination~~ → keine, vermutlich Voll-Dump.
5. ~~Granularität & Feldnamen~~ → **weder** "wide Stecker1..6" **noch** "schon
   flach pro Ladepunkt", sondern ein dritter Fall: verschachtelte Baumstruktur
   Station → Evse → Connector. Erfordert eigenes Flatten (Abschnitt 3), keine
   Wiederverwendung von `transform()`.
6. ~~Datumsformat~~ → **weder** Epoch-ms **noch** ISO-String, sondern
   `dd.MM.yyyy` als deutsches Datumsformat.
7. ~~Datenstand-Feld~~ → ja, `documentDate`/`documentTime`.
8. Nutzungsbedingungen → aus der Begleit-Mail (nicht der Spec): CC BY 4.0 mit
   Namensnennung "Bundesnetzagentur.de" (bereits abgedeckt, s.
   `01_app/sections/info.py:40`), kein Verfügbarkeits-SLA, nicht-exklusives/
   nicht übertragbares Nutzungsrecht.

**Weiterhin offen (nicht aus der Spec ableitbar, nur live verifizierbar):**
- Tatsächliche Antwortgröße/Datensatzzahl (für den `MIN_RECORDS`-Guard, s.
  Abschnitt 4 — **nicht** blind die ~50.000-Schwelle aus dem ArcGIS-Plan
  übernehmen, die war für eine andere Quelle mit ~109k Stationen kalibriert).
- Ob `companyName` wirklich der richtige `Betreiber`-Wert ist (s. Tabelle oben).
- Ob echte Requests tatsächlich ohne Auth funktionieren.

---

## 3. Code-Struktur

Minimaler Eingriff, an `update_data_api.py` (ArcGIS-Variante) angelehnt. Neue Datei:
```text
scripts/update_data_official.py
```
- Importiert `add_ags`, `OUT_PATH`, `VERSION_PATH`, `SHAPEFILE` aus `update_data`
  (nicht `transform()` — passt nicht zur verschachtelten Struktur, s. o.).
- **`fetch_all() -> dict`:** einzelner `requests.get(API_URL, timeout=60)` mit
  Retry/Backoff (z. B. 3 Versuche); `404` → eigene Exception ("Export noch
  nicht bereitgestellt"), sauber geloggt, kein Absturz mit generischem Traceback;
  `response.json()`.
- **`build_target(data: dict) -> pd.DataFrame`:** ersetzt `transform()`. Läuft
  über die verschachtelte Struktur und baut **eine Zeile pro Connector**
  (gleiche Granularität wie der bisherige Melt über `Steckertypen1..6`):
  ```python
  rows = []
  for station in data["chargingStations"]:
      anzahl_ladepunkte = len(station.get("evses", []))
      base = {
          "ladestation_id": station["id"],
          "Betreiber": station["operator"]["companyName"],
          "Strasse": station.get("street"),
          "Hausnummer": station.get("house_no"),
          "Adresszusatz": station.get("address_addition"),
          "PLZ": station.get("postal_code"),
          "Ort": station.get("city"),
          "Bundesland": station.get("state"),
          "KreisKreisfreieStadt": station.get("district_independent_city"),
          "Breitengrad": station["coordinates"]["latitude"],
          "Laengengrad": station["coordinates"]["longitude"],
          "Inbetriebnahmedatum": station.get("go_live_date"),
          "InstallierteLadeleistungNLL": station.get("max_electric_power_station"),
          "ArtLadeeinrichtung": station.get("type"),
          "AnzahlLadepunkteBNetzA": anzahl_ladepunkte,
      }
      for evse in station.get("evses", []):
          for connector in evse.get("connectors", []):
              row = {
                  **base,
                  "Steckertyp": connector.get("connector_type"),
                  "LadeleistungInKW": connector.get("max_electric_power_connector"),
                  "ladepunkt_id": f"{evse['evse_id']}#{connector.get('connector_type', '')}",
              }
              rows.append(row)

  df = pd.DataFrame(rows)
  df["Inbetriebnahmedatum"] = pd.to_datetime(df["Inbetriebnahmedatum"], format="%d.%m.%Y", errors="coerce")
  df["BetreiberBereinigt"] = df["Betreiber"]
  df["NennleistungBNetzA"] = df["InstallierteLadeleistungNLL"]
  df["LadeUseCase"] = "Unbekannt"
  ```
  (Feinschliff/Fehlerbehandlung bei fehlenden Keys noch zu ergänzen —
  Struktur oben zeigt das Prinzip.)
- **`main()`:** `fetch_all` → `build_target` → `add_ags` → `to_parquet` →
  `VERSION_PATH.write_text(f'LAST_UPDATED = "{documentDate}"\n')` (Datum aus
  der API-Antwort, auf `YYYY-MM-DD` normalisiert).

---

## 4. Validierung / Robustheit (zwingend, wie bisher)
- Pflicht-Spalten nach `build_target` prüfen.
- `MIN_RECORDS`-Schwelle **neu kalibrieren** anhand eines echten Testlaufs
  (nicht die ~50.000 aus dem ArcGIS-Plan übernehmen — andere Quelle, andere
  Grundgesamtheit, siehe "Beschränkung auf abgeschlossene Anzeigeverfahren" in
  der Mail, die Zahl kann durchaus kleiner sein als die 109k vom Snapshot).
- Plausi-Diff gegen die aktuelle Parquet: Stations-/Ladepunkt-Zahl,
  `max(Inbetriebnahmedatum)` sollte neuer sein.
- Globales `try/except` → `sys.exit(1)` bei `404`/`500`/Netzwerkfehler/zu
  wenigen Datensätzen — kein Commit eines kaputten Standes.

## 5. CI / Workflow
- `.github/workflows/update_data_api.yml` (täglicher Cron existiert bereits
  für die ArcGIS-Variante) auf `uv run python scripts/update_data_official.py`
  umstellen.
- Kein Token-Secret nötig, solange Punkt "Auth" sich live bestätigt.
- `update_data.py` (XLSX, monatlich) als Fallback behalten, bis die offizielle
  API über mehrere Läufe verifiziert ist.

## 6. Test & Rollout
1. Lokal: aktuelle Parquet + `_data_version.py` sichern.
2. Einmal `curl`/`requests` gegen den Endpoint fahren **ohne** Auth-Header —
   prüfen: Status 200? Antwortgröße? Tatsächliche Stationszahl?
3. `uv run python scripts/update_data_official.py` — Logs/Recordzahl prüfen.
4. Schema-Diff gegen Referenz: Spalten, dtypes, NaN-Quote der Schlüsselspalten.
5. `PYTHONPATH=01_app uv run python -c "from data_loading import load_data; …"`
   → `Jahr`/`Leistungskategorie` plausibel.
6. Erst dann committen/Workflow scharf schalten. PR ohne AI-Attribution.

## 7. Entscheidungen — jetzt mit Empfehlung

- [x] **Granularität:** eine Zeile pro Connector (analog zum bisherigen Melt),
      `AnzahlLadepunkteBNetzA` separat als `len(evses)` berechnet — nicht mit
      der Zeilenzahl verwechseln, das sind zwei unterschiedliche Zählungen.
- [x] **`ladepunkt_id`:** stabile Kombination `evse_id` + `connector_type`
      statt laufender Nummer — `evse_id` (z. B. `DE*BNA*E12345*01`) ist über
      Tagesläufe hinweg stabil, eine reine `range(1, len(df))`-Nummer wäre es
      nicht (verschiebt sich bei jeder Sortierreihenfolgen-Änderung).
- [ ] `services2`-Skript & XLSX-Pipeline: behalten / abschalten / löschen —
      weiterhin offen, erst nach ein paar stabilen Läufen der neuen API
      entscheiden.
- [ ] Cron-Frequenz: täglich, sobald Live-Test (Abschnitt 6.2) unauffällig war.
