# update_data_official.py — Erklärung

Begleitdokument zu `scripts/update_data_official.py`. Es erklärt nicht nur, *was*
das Skript tut, sondern *warum* es so gebaut ist, und benennt die allgemeinen
Muster dahinter — gedacht zum Nachlesen und Lernen, nicht als Referenz.

Der Ausführplan mit der Entscheidungshistorie liegt in
`plans/2026-06-26_offizielle-api-implementierung.md`. Dieses Dokument beschreibt
den Stand, wie er implementiert ist.

---

## 1. Einordnung

Es gibt zwei Wege, an die BNetzA-Ladesäulendaten zu kommen:

| | `update_data.py` (bisher) | `update_data_official.py` (neu) |
|---|---|---|
| Quelle | XLSX-Datei von der BNetzA-Downloadseite | offizielle JSON-API |
| Aktualität | monatlich | täglich |
| Beschaffung | HTML der Downloadseite nach dem XLSX-Link durchsuchen (Scraping) | fester, dokumentierter Endpunkt |
| Form der Rohdaten | flache Tabelle mit breiten Spalten | verschachtelter Baum |
| Status | produktiv (Workflow `update_data.yml`) | produktiv (Workflow `update_data_api.yml`) |

Beide schreiben **dasselbe Zielschema an dieselben Pfade**
(`02_data/03_computed_data/combined_ladestation_ladepunkt.parquet` und
`01_app/_data_version.py`). Das ist Absicht: die App muss nicht wissen, aus
welcher Quelle die Daten kamen. Man kann die Quelle austauschen, ohne eine Zeile
im Dashboard anzufassen.

Warum das wichtig ist: die Schnittstelle zwischen Datenpipeline und App ist
**das Parquet-Schema**, nicht das Skript. Solange das Schema stabil bleibt, sind
beide Seiten unabhängig voneinander änderbar. Genau deshalb ist die Spaltenliste
`REQUIRED_COLUMNS` im Skript explizit hingeschrieben und wird am Ende von
`build_target()` als Projektion angewandt (`return df[REQUIRED_COLUMNS]`) — sie
ist der Vertrag, nicht bloß Doku.

---

## 2. Die API

Endpunkt:

```
GET https://ladesaeulenregister.bnetza.de/els/service/public/v1/chargepoints
```

Keine Authentifizierung, keine Parameter. Messung vom 01.08.2026: 116,3 MB,
115.613 Stationen, rund 52 Sekunden.

### 2.1 GET ist "safe" — warum das praktisch relevant ist

Die HTTP-Spezifikation teilt Methoden in *safe* und *unsafe* ein. Ein `GET` ist
safe: es darf serverseitig **keinen Zustand verändern**. Es fragt nur "wie sieht
die Ressource gerade aus" und bekommt bis zur nächsten Veröffentlichung dieselbe
Antwort.

Die praktische Konsequenz: dieses Skript und jede Probe während der Entwicklung
darf man **beliebig oft wiederholen**. Es gibt kein aufgebrauchtes Kontingent,
keine doppelt angelegten Datensätze, keine halb ausgeführte Transaktion.

Bei `POST`, `PUT` oder `DELETE` wäre das anders: ein Skript, das nach einem
Timeout blind neu gestartet wird, könnte dort Daten doppelt anlegen oder
zerstören. Deshalb ist "einfach nochmal laufen lassen" nur bei safe Methoden ein
legitimes Vorgehen — bei unsafe Methoden braucht man **Idempotenz-Schlüssel**
oder eine serverseitige Deduplizierung, damit ein Retry gefahrlos ist.

### 2.2 Content Negotiation

```python
headers = {"Accept": "application/json"}
```

Derselbe Endpunkt kann laut Spec auch XML liefern. Welche Repräsentation der
Server zurückgibt, verhandeln Client und Server über den `Accept`-Header — das
nennt man **Content Negotiation**. Die URL identifiziert *die Ressource*, der
Header wählt *das Format*.

Man könnte den Header weglassen und sich auf den Default verlassen. Ihn explizit
zu setzen kostet nichts und schützt davor, dass eine serverseitige
Default-Änderung das Skript still auf XML umstellt — dann würde `response.json()`
knallen statt falsche Daten zu liefern, aber erst nach dem 116-MB-Download.

### 2.3 Das Envelope-Pattern

Die Antwort ist **kein** nacktes JSON-Array von Stationen. Sie sieht so aus:

```json
{
  "documentDate": "01.08.2026",
  "documentTime": "06:00:00",
  "chargingStations": [ ... ]
}
```

Die eigentliche Nutzlast steckt eine Ebene tiefer, umgeben von Metadaten. Dieses
Muster heißt **Envelope** (Umschlag) oder *response wrapper*: Metadaten, die die
Nutzlast beschreiben, reisen mit der Nutzlast statt separat (z. B. in einem
HTTP-Header oder über einen zweiten Request).

Vorteil: der Datenstand (`documentDate`) ist untrennbar mit den Daten verbunden.
Das Skript nutzt genau das — es leitet den Stempel für `_data_version.py` aus
`documentDate` ab, statt "heute" anzunehmen. Wäre das Datum nur ein HTTP-Header,
ginge es beim Zwischenspeichern der Antwort verloren.

Der Preis: man muss den Umschlag öffnen, bevor man an die Daten kommt:

```python
stations = data["chargingStations"]
```

Wenn eine API-Antwort dich unerwartet mit einem Objekt statt einer Liste
begrüßt, ist fast immer ein Envelope der Grund.

### 2.4 Keine Pagination — und warum das ein Risiko bleibt

Große Listen liefern APIs üblicherweise seitenweise aus (`?page=`, `?offset=`,
Cursor). Diese hier nicht: die OpenAPI-Spec definiert keine solchen Parameter,
und die Live-Probe hat es bestätigt — ein Request, alle 115.613 Stationen.

Das Skript pagniert deshalb nicht. Der Kommentar im Modul-Docstring warnt aber
bewusst davor, dass das eine **Annahme über die Zukunft** ist. Der gefährliche
Fall wäre nicht "API führt Pagination ein und das Skript bricht" — das würde
auffallen. Der gefährliche Fall ist: die API führt einen *optionalen*
`page`-Parameter mit Default `page=1, size=1000` ein. Dann läuft das Skript
weiter durch, meldet Erfolg und speichert 1.000 statt 115.613 Stationen.

Genau gegen diese Klasse von Fehlern arbeitet die Validierung in Abschnitt 4.
Merksatz: **Annahmen über externe Systeme brauchen eine Prüfung, die anschlägt,
wenn die Annahme kippt.** Ein Kommentar allein reicht nicht.

### 2.5 Fehlerbehandlung: transient oder nicht?

```python
class ExportNotReadyError(RuntimeError):
    """Raised on HTTP 404: BNetzA has not published today's export yet."""
```

Das Skript behandelt zwei Fehlerarten unterschiedlich, und das ist der
eigentliche Denkschritt:

- **HTTP 404** heißt laut Spec: der Export für heute existiert noch nicht. Das
  ist kein Defekt, und es löst sich nicht in fünf Sekunden. Ein Retry würde nur
  Zeit verbrennen und die Fehlermeldung verzögern. Also: sofort abbrechen.
- **HTTP 500 oder ein Netzwerkfehler** kann ein kurzer Aussetzer sein — ein
  Server-Hänger, eine abgerissene Verbindung. Das ist ein Kandidat für einen
  Retry.

Umgesetzt ist das über die Vererbungshierarchie, ohne zusätzliche Fallunter-
scheidung: `ExportNotReadyError` erbt von `RuntimeError`, der Retry-Handler
fängt `requests.RequestException` (die von `OSError` erbt). Die beiden Zweige
sind disjunkt, also verlässt der 404 die Schleife von selbst.

> Das war in der ersten Fassung noch mit einem zusätzlichen
> `except ExportNotReadyError: raise` abgesichert. Diese Klausel konnte nie
> greifen und ist im Review entfernt worden — ein gutes Beispiel dafür, dass
> "sicherheitshalber noch ein Handler" oft nur Rauschen ist, wenn man sich die
> Klassenhierarchie tatsächlich ansieht.

Der Backoff ist linear (`5, 5` Sekunden bei 3 Versuchen). Für einen
Tages-Cronjob reicht das. **Exponentielles Backoff** (1, 2, 4, 8 …), gerne mit
zufälligem *Jitter*, ist die übliche Empfehlung, wenn viele Clients gleichzeitig
gegen denselben überlasteten Dienst laufen — sie sollen sich nicht im Gleichtakt
neu synchronisieren. Bei genau einem Client pro Tag ist dieser Effekt
gegenstandslos.

---

## 3. Vom Baum zur Tabelle

### 3.1 Das Datenmodell der API

Die Rohdaten sind ein Baum mit drei Ebenen, jeweils 1:n:

```
ChargingStation          (Ladestation, ein Standort)
└── Evse                 (Ladepunkt: was gleichzeitig ein Auto laden kann)
    └── Connector        (Steckervariante an diesem Ladepunkt)
```

Die Begriffe sind branchenüblich und lohnen sich:

- **Station**: der physische Standort, das, was man als "Ladesäule" sieht.
- **EVSE** = *Electric Vehicle Supply Equipment*. Das ist die Einheit, die genau
  ein Fahrzeug gleichzeitig laden kann. In der deutschen BNetzA-Terminologie:
  **Ladepunkt**.
- **Connector**: der einzelne Stecker. Ein EVSE kann mehrere Connectors haben
  (z. B. CCS und Typ 2 am selben Kabelabgang) — aber es kann trotzdem nur ein
  Auto gleichzeitig laden. Deshalb sind zwei Connectors **nicht** zwei
  Ladepunkte.

Dieser letzte Punkt ist die häufigste Verwechslung in dem Datensatz und der
Grund für den Kommentar an `AnzahlLadepunkteBNetzA` im Code.

### 3.2 Flattening

Das Dashboard braucht eine flache Tabelle, eine Zeile pro Connector. Aus einem
Baum eine Tabelle zu machen ist ein Standard-ETL-Schritt und heißt
**Flattening** (auch: Denormalisierung). Das Prinzip: für jedes Blatt des Baums
eine Zeile erzeugen und die Werte der Elternknoten dabei **wiederholen**.

Im Code sind das die drei verschachtelten Schleifen in `build_target()`:

```python
for station in stations:
    base = { ... }                          # Stationswerte, einmal berechnet
    for idx, evse in enumerate(evses):
        for connector in evse.get("connectors", []):
            rows.append({**base, ...})      # base wird pro Zeile wiederholt
```

`{**base, ...}` ist *dictionary unpacking*: die Stationsfelder werden in jedes
Zeilen-Dict hineinkopiert. Dass die Stationsdaten redundant in jeder Zeile
stehen, ist bei einem analytischen Datensatz gewollt — man tauscht Speicher
gegen den Wegfall von Joins zur Abfragezeit.

`update_data.py` löst dasselbe Grundproblem in anderer Form: die XLSX hatte
**breite** Spalten `Steckertypen1` bis `Steckertypen6` (eine Stationszeile, bis
zu sechs Steckerplätze nebeneinander) und macht daraus mit einem Melt eine Zeile
pro Stecker. Andere Ausgangsform, identisches Ziel. Wide-to-long und
Tree-to-flat sind zwei Gesichter derselben Aufgabe.

Deshalb kann `build_target()` `transform()` auch **nicht** wiederverwenden: der
Zielzustand ist gleich, der Weg dorthin nicht.

### 3.3 Zeilenaufbau und Listen statt DataFrame-Wachstum

`rows` ist eine Python-Liste von Dicts, aus der am Ende **einmal** ein DataFrame
gebaut wird:

```python
df = pd.DataFrame(rows)
```

Das ist kein Stilzufall. Ein DataFrame zeilenweise wachsen zu lassen (`df.loc[len(df)] = ...`
oder `pd.concat` in der Schleife) kopiert bei jedem Schritt den gesamten
bisherigen Datenrahmen — quadratischer Aufwand. Bei 218.000 Zeilen ist der
Unterschied zwischen "eine Sekunde" und "mehrere Minuten". Faustregel:
**in Python-Strukturen sammeln, einmal in pandas übergeben.**

### 3.4 Der Schlüssel `ladepunkt_id`

Der Plan sah vor: `ladepunkt_id = f"{evse_id}#{connector_type}"`.

Der Blick in die echten Daten hat das gekippt: **`evse_id` ist bei rund 70 % der
Evses `null`.** Aus der Formel wären damit zehntausende identische Schlüssel
`None#Typ2` geworden.

Die Lösung im Code:

```python
evse_key = evse.get("evse_id") or f"{station['id']}-{idx}"
```

Fehlt die `evse_id`, tritt eine **positionsbasierte Ersatz-ID** an ihre Stelle,
die auf die Station begrenzt ist. Warum stationsbezogen und nicht ein globaler
Zähler wie in `update_data.py` (`range(1, len(df) + 1)`)? Weil ein globaler
Zähler bei jedem Lauf andere IDs vergibt, sobald sich irgendwo die Reihenfolge
ändert. Der stationsbezogene Schlüssel ändert sich nur, wenn sich an *dieser*
Station etwas ändert.

Zwei Dinge dazu, ehrlich benannt:

1. Der Schlüssel ist nicht garantiert eindeutig. Hat ein EVSE zweimal denselben
   `connector_type`, entstehen zwei identische IDs. Aktuell unkritisch, weil
   nichts in `01_app/` auf `ladepunkt_id` zugreift — die Spalte existiert nur
   zur Schemagleichheit mit der XLSX-Pipeline.
2. Das ist die allgemeinere Lektion: **Feldbeschreibungen in einer Spec sagen
   nichts über die Befüllung in der Praxis.** Ein Feld kann als Identifikator
   dokumentiert und trotzdem meistens leer sein. Schlüsselkandidaten gehören an
   echten Daten geprüft, nicht an der Dokumentation.

### 3.5 Feld-Mapping

| API-Feld | Zielspalte | Anmerkung |
|---|---|---|
| `id` | `ladestation_id` | JSON liefert `int`, die XLSX lieferte `str` — bewusster Dtype-Wechsel |
| `operator.companyName` | `Betreiber`, `BetreiberBereinigt` | `displayName` wäre der Kurzname |
| `street` | `Strasse` | |
| `house_no` | `Hausnummer` | |
| `address_addition` | `Adresszusatz` | |
| `postal_code` | `PLZ` | |
| `city` | `Ort` | |
| `state` | `Bundesland` | |
| `district_independent_city` | `KreisKreisfreieStadt` | |
| `coordinates.latitude` | `Breitengrad` | nativ `double`, kein String-Parsing nötig |
| `coordinates.longitude` | `Laengengrad` | s. o. |
| `go_live_date` | `Inbetriebnahmedatum` | String `"dd.MM.yyyy"`, siehe 4.4 |
| `max_electric_power_station` | `InstallierteLadeleistungNLL`, `NennleistungBNetzA` | **kW**, nicht W |
| `type` | `ArtLadeeinrichtung` | `Normalladeeinrichtung` / `Schnellladeeinrichtung` |
| `len(evses)` | `AnzahlLadepunkteBNetzA` | berechnet, kein API-Feld |
| `evses[].connectors[].connector_type` | `Steckertyp` | eigenes Enum, Werte weichen von der XLSX ab |
| `evses[].connectors[].max_electric_power_connector` | `LadeleistungInKW` | nativ `double`, **kW** |
| — | `LadeUseCase` | konstant `"Unbekannt"`, wie in der XLSX-Pipeline |
| — | `ARS` | kommt aus dem Geo-Join, siehe Abschnitt 5 |

Zur Einheit **kW**: `01_app/sections/kpis.py` summiert
`InstallierteLadeleistungNLL` und teilt durch 1.000.000, um GW anzuzeigen, und
vergleicht `LadeleistungInKW` gegen `HPC_THRESHOLD_KW`. Käme das Feld in Watt,
wäre jede Leistungs-KPI um Faktor 1.000 daneben — ohne dass irgendetwas
abstürzt. Deshalb steht die Einheit als Kommentar im Code: sie ist eine
**stille Annahme mit großer Hebelwirkung**.

### 3.6 Direkter Zugriff vs. `.get()`

Im Code fällt der gemischte Stil auf:

```python
"ladestation_id": station["id"],                        # knallt bei Fehlen
"Betreiber": station["operator"]["companyName"],        # knallt bei Fehlen
"Strasse": station.get("street"),                       # wird zu None
```

Das ist Absicht. `station["id"]` und `coordinates` sind laut Spec Pflichtfelder
und in den echten Daten zu 100 % befüllt. Fehlt eines, hat sich das Payload-
Format geändert — und dann ist ein sofortiger `KeyError` das gewünschte
Verhalten. Eine Adresszeile dagegen darf legitim fehlen; dort wäre ein Absturz
falsch.

Die Regel dahinter: **Nachsichtig sein, wo Lücken normal sind. Laut scheitern,
wo eine Lücke bedeutet, dass die eigene Annahme falsch ist.** Wer überall
`.get()` schreibt, verwandelt Strukturbrüche in stille `None`-Werte, die erst
drei Schritte später als unerklärlicher Fehler auftauchen.

---

## 4. Validierung: "trust but verify"

Externe Daten können fehlerhaft sein, ohne dass der HTTP-Request scheitert. Ein
Status 200 sagt "die Übertragung hat geklappt", nicht "der Inhalt ist richtig".
Der schlimmste Fall ist nicht die kaputte Antwort — die fällt auf. Es ist die
**plausibel aussehende, aber falsche** Antwort.

### 4.1 Reihenfolge ist die halbe Miete

In `main()`:

```python
df_previous = pd.read_parquet(OUT_PATH) if OUT_PATH.exists() else None
validate(df, df_previous)
df = add_ags(df)
save_output(df, ...)
```

Zwei Reihenfolge-Entscheidungen stecken darin:

1. **Lesen vor Schreiben.** Der alte Stand muss eingelesen sein, *bevor*
   `save_output()` ihn überschreibt. Danach wäre der letzte bekannte gute Stand
   weg, und eine Prüfung könnte Beschädigung nur noch feststellen, nicht
   verhindern. Das ist der Unterschied zwischen einer **Vorbedingung** und einem
   Nachruf.
2. **Prüfen vor teuer.** Der Geo-Join (`add_ags`) ist der teuerste Schritt.
   Ihn erst nach der Validierung laufen zu lassen, spart bei einem kaputten
   Export Minuten. Allgemein: billige Prüfungen nach vorn, teure Arbeit nach
   hinten.

### 4.2 Absolute und relative Schwelle

```python
MIN_RECORDS = 100_000
PLAUSIBILITY_MIN_RATIO = 0.9
```

Zwei Prüfungen, die verschiedene Dinge abfangen:

- Die **absolute** Untergrenze ist ein harter Boden, unabhängig von jedem
  Vorzustand. Sie schlägt an bei "leere Antwort", "abgeschnittener Export",
  "falscher Endpunkt". Sie liegt mit 100.000 gegenüber den beobachteten 115.613
  bewusst deutlich darunter (ca. 87 %) und nicht knapp daneben — eine Schwelle,
  die bei normaler Schwankung Fehlalarm auslöst, wird nach dem dritten Mal
  ignoriert oder entfernt. **Eine Prüfung, der niemand mehr glaubt, ist
  schlechter als keine.**
- Die **relative** Prüfung vergleicht gegen den letzten gespeicherten Stand. Sie
  fängt den schleichenden Fall: nicht "alles weg", sondern "ein Drittel fehlt".
  Für den absoluten Boden wäre das noch unauffällig.

Beide zusammen decken zwei verschiedene Ausfallarten ab. Das ist der Grund für
die scheinbare Doppelung.

### 4.3 Harte Fehler und Warnungen

Die Prüfungen sind bewusst **asymmetrisch**:

- Stationszahl bricht ein → `ValueError`, Abbruch. Das Register wächst oder
  stagniert; ein plötzlicher Rückgang hat keine legitime Erklärung.
- Jüngstes `Inbetriebnahmedatum` ist älter als zuvor → nur eine Warnung. Dass
  seit gestern keine Station in Betrieb ging, ist völlig normal. Ein Abbruch
  wäre hier Fehlalarm.

Die Leitfrage bei jeder Prüfung: *Gibt es eine harmlose Erklärung für dieses
Signal?* Wenn ja, ist es eine Warnung. Wenn nein, darf es abbrechen.

### 4.4 Der NaT-Guard und die Region-Spalten

```python
MAX_NAT_RATIO = 0.05
MAX_MISSING_REGION_RATIO = 0.05
```

`build_target()` parst das Datum mit
`pd.to_datetime(..., format="%d.%m.%Y", errors="coerce")`. `errors="coerce"`
heißt: was nicht passt, wird zu `NaT` (*Not a Time*) statt eine Exception zu
werfen — sinnvoll bei einzelnen kaputten Werten.

Der Haken: stellt die API auf ISO-Format (`"2026-08-01"`) um, passt **kein**
Wert mehr auf das Format, und *jedes* Datum wird still zu `NaT`. Das Skript
liefe durch, meldete Erfolg, und im Dashboard wären sämtliche Jahres- und
Zubau-Auswertungen leer. Die vorhandene Datumsprüfung hätte es nicht bemerkt:
ein Vergleich mit `NaT` ergibt immer `False`, also nicht mal die Warnung.

Der Guard prüft deshalb den **Anteil** der `NaT`-Werte. Das ist wieder das
Muster aus 2.4: eine Annahme über ein fremdes System (hier das Datumsformat)
bekommt eine Prüfung, die anschlägt, wenn die Annahme kippt.

Allgemein: `errors="coerce"` ist bequem und deshalb gefährlich. Wer Fehler zu
`NaN`/`NaT` verwandelt, muss danach die Quote messen — sonst hat man
Fehlerbehandlung nur simuliert.

**Warum die Schwelle bei 5 % liegt und nicht bei 50 %.** Die erste Fassung
erlaubte `MAX_NAT_RATIO = 0.5`. Das war zu großzügig gedacht — der Guard sollte
nur den totalen Formatbruch abfangen, bei dem *jeder* Wert zu `NaT` wird.
Übersehen wurde dabei die Gegenseite: `01_app/data_loading.py` wirft beim Laden
jede Zeile weg, deren `Inbetriebnahmedatum`, `Bundesland` oder
`KreisKreisfreieStadt` leer ist. Bei 50 % erlaubter `NaT`-Quote hätte ein
**grüner** Lauf also das halbe Dashboard leeren können, ohne dass irgendwo ein
Fehler auftaucht.

Dieselbe Falle gilt für die beiden Regionsspalten, und dort ist sie
wahrscheinlicher: `state` und `district_independent_city` sind optionale
API-Felder, werden also mit `.get()` gelesen und dürfen legitim `None` sein.
`add_ags()` füllt sie nicht auf — der Geo-Join setzt nur `ARS`.

Die Schwelle ist an der bestehenden Quelle geeicht: im produktiven Parquet aus
der XLSX-Pipeline sind alle drei Spalten zu **100 %** befüllt (204.078 Zeilen,
kein einziger Verlust beim `dropna` der App). 5 % liegen damit weit außerhalb
des Normalen und trotzdem nicht so knapp, dass einzelne Lücken Fehlalarm
auslösen.

> Das Muster dahinter: eine Prüfung in der Pipeline ist nur so gut, wie sie zu
> dem passt, was der *Konsument* der Daten damit macht. Eine Schwelle, die
> isoliert plausibel klingt, kann trotzdem falsch sein, wenn man die
> Weiterverarbeitung nicht kennt.

---

## 5. Wiederverwendung aus `update_data.py`

```python
from update_data import add_ags, save_output, OUT_PATH, SHAPEFILE
```

Geteilt werden die Teile, die **quellenunabhängig** sind:

- `OUT_PATH`, `SHAPEFILE` — Pfade. Zweimal denselben String zu pflegen ist eine
  Fehlerquelle, sobald sich einer ändert.
- `add_ags(df)` — der räumliche Join: für jeden Punkt (Längen-/Breitengrad) wird
  über das Kreis-Shapefile der Amtliche Gemeindeschlüssel bestimmt (*Point in
  Polygon*, `gpd.sjoin(..., predicate="within")`). Das hängt nur an den
  Koordinaten, nicht an der Herkunft der Daten.
- `save_output(df, datenstand)` — Parquet schreiben und `_data_version.py`
  stempeln. Diese Funktion ist im Review entstanden: beide Skripte hatten den
  Block vorher wortgleich.

Nicht geteilt wird `transform()`, siehe 3.2 — gleiche Absicht, andere
Ausgangsform.

Der Import funktioniert, weil beim Start von `scripts/update_data_official.py`
das Verzeichnis `scripts/` in `sys.path` landet. Ausgeführt wird trotzdem **aus
dem Repo-Root**, weil alle Pfade relativ zum Arbeitsverzeichnis sind.

---

## 6. Exit-Code und Cron-Betrieb

```python
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)
```

Ein pauschales `except Exception` ist normalerweise ein Warnzeichen. Hier ist es
richtig, und zwar genau an dieser Stelle: am **Einstiegspunkt** eines Skripts,
das von einem Automaten aufgerufen wird.

Der Grund liegt außerhalb von Python. Ein GitHub-Actions-Workflow entscheidet am
**Exit-Code**, ob ein Schritt erfolgreich war. Läuft das Skript in einen
unbehandelten Fehler und der Workflow prüft das nicht sauber, könnte der
nachgelagerte Commit-Schritt trotzdem laufen und einen kaputten Zwischenstand
festschreiben. Exit-Code 1 stellt sicher: **kein Erfolg, kein Commit.**

Zwei Details, die dazugehören:

- Die Meldung geht auf `stderr`, nicht `stdout`. Log-Systeme trennen die beiden.
- `except Exception` fängt bewusst nicht `BaseException` — `KeyboardInterrupt`
  und `SystemExit` sollen weiterhin durchgehen.

---

## 7. Bekannte Grenzen

- **Roter Lauf, wenn der Export fehlt.** `update_data_api.yml` läuft täglich um
  07:20 UTC. Hat die BNetzA den Export des Tages noch nicht bereitgestellt,
  endet der Lauf mit HTTP 404 und Exit-Code 1 — also mit einem fehlgeschlagenen
  Workflow, obwohl nichts kaputt ist. Bewusst so gelassen, bis über ein paar
  Läufe klar ist, wie oft das vorkommt. `update_data.py` bleibt als monatlicher
  Fallback bestehen.
- **`status.operational` wird nicht ausgewertet.** Die API kennt einen
  Betriebsstatus, die XLSX-Quelle nicht. Bewusst nicht gemappt, um keine
  stillschweigende Verhaltensänderung im Dashboard einzuführen.
- **Dtype-Wechsel gegenüber der XLSX-Quelle:** `ladestation_id` und
  `AnzahlLadepunkteBNetzA` werden `int64` statt `object`, `ladepunkt_id` wird
  `object` statt `int64`. Die App ist davon nicht betroffen (sie nutzt
  `nunique()` und `drop_duplicates()`), aber wer eigene Auswertungen auf dem
  Parquet fährt, sollte es wissen.
- **`Steckertyp` nutzt ein anderes Enum** als die XLSX-Quelle. Bei einem
  Quellenwechsel ändern sich also die Kategorienamen in den Filtern.

---

## 8. Lokal ausführen

```bash
uv run python scripts/update_data_official.py
```

Aus dem Repo-Root, sonst greifen die relativen Pfade ins Leere.

**Achtung:** ein erfolgreicher Lauf überschreibt
`02_data/03_computed_data/combined_ladestation_ladepunkt.parquet` und
`01_app/_data_version.py`. Beide liegen im Git — vor einem Testlauf also
sicherstellen, dass keine ungesicherten Änderungen im Weg sind, und danach mit
`git checkout -- <pfad>` zurücksetzen, wenn die Daten nicht mitcommittet werden
sollen.
