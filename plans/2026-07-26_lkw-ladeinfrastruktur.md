# Ausführplan: Lkw-Ladeinfrastruktur (Mobilithek) ins Dashboard integrieren

Status: **Entwurf zur Diskussion** (noch nicht umgesetzt, noch kein Issue).

## Ziel
Die öffentlich zugänglichen **Lkw-Ladestandorte** (Datenangebot der Nationalen
Leitstelle Ladeinfrastruktur auf der Mobilithek) als zweite Infrastruktur-Ebene
neben dem Pkw-Bestand aus dem BNetzA-Ladesäulenregister sichtbar machen:
eigener Tab "Lkw-Laden" mit KPIs, Standortkarte und regionaler Verteilung,
gefüttert aus einer eigenen, automatisiert aktualisierten Parquet-Datei.

## Ausgangslage im Repo
- `scripts/update_data.py` (BNetzA-XLSX) und `scripts/update_kba_data.py` (KBA-API)
  schreiben je eine Parquet-Datei in `02_data/03_computed_data/` und werden von
  je einem GitHub-Actions-Workflow committet.
- `01_app/data_loading.py::load_all()` lädt drei Quellen (Register, Shapefile, KBA).
- `01_app/app.py` rendert fünf Tabs: Überblick, Analysen, Landkreise, Daten, Hinweise.
- Das Ladesäulenregister enthält **keine** Lkw-Attribute (keine Stellplatzlänge,
  keine Durchfahrtsmöglichkeit, kein Fahrzeugklassen-Feld). Lkw-Eignung lässt sich
  daraus nicht sauber ableiten -> externe Quelle ist notwendig, nicht optional.

## Phase 0 — Quelle verifizieren (Spike, blockiert alles Weitere)
Muss lokal oder in einem CI-Job laufen (Sandbox hat keinen Zugriff auf
mobilithek.info). Ergebnis als Notebook `03_notebooks/05_exploration_lkw_data.ipynb`
plus kurze Notiz in diesem Plan.

Zu klären:
1. **Welches Datenangebot genau?** Offer-ID, Titel, Herausgeber. Kandidaten:
   das aufbereitete Ladesäulenregister der Leitstelle (Offer 842113170303512576,
   aus dem die ursprünglichen Take-home-CSVs stammen — enthält Lade-Use-Cases/
   Kategorien) vs. ein separates Lkw-Datenangebot hinter dem
   Lkw-LadeinfrastrukturMONITORING.
2. **Zugriffsweg:** Direkter Download-Link (Open Data) oder Abo-Angebot mit
   Registrierung/Client-Zertifikat? Davon hängt ab, ob die Pipeline anonym in
   Actions laufen kann oder GitHub Secrets bzw. ein manueller Snapshot nötig sind.
3. **Format & Granularität:** CSV/JSON/DATEX II; Standort- oder Ladepunkt-Ebene;
   Zeilenzahl (Erwartung: einige hundert Standorte, keine sechsstellige Menge).
4. **Felder:** Koordinaten, Betreiber, Ladeleistung je Ladepunkt, Anzahl
   Lkw-geeigneter Ladepunkte, Stellplatzlänge (Kriterium wurde von 12 m auf
   16,5 m verschärft), Durchfahrtsmöglichkeit, Inbetriebnahmedatum (entscheidet,
   ob eine Zeitreihe möglich ist), Bundesland/Kreis oder nur Geokoordinaten.
5. **Join-Fähigkeit:** Gibt es eine ID, die zu `ladestation_id` (BNetzA
   Ladeeinrichtungs-ID) passt? Sonst Koordinaten-Matching (Nachbar < 100 m).
6. **Lizenz & Aktualisierung:** Weitergabe im Repo erlaubt (DL-DE/BY-2.0, CC-BY)?
   Nennung in `sections/info.py` erforderlich? Update-Intervall der Quelle.

Abbruchkriterium: ist der Datensatz nur mit Anmeldung/Zertifikat beziehbar,
wird Phase 1 auf "manueller Snapshot + dokumentiertes Refresh-Verfahren"
reduziert, statt die Pipeline zu erzwingen.

## Phase 1 — Pipeline
Neu: `scripts/update_lkw_data.py` -> `02_data/03_computed_data/lkw_ladeinfrastruktur.parquet`

- Aufbau analog `update_kba_data.py`: `download()` -> `transform()` -> `to_parquet()`,
  deutsche Print-Ausgaben, `requests` mit Timeout.
- Zielschema (Arbeitsstand, Standort-Ebene):
  `lkw_standort_id, Betreiber, Strasse, PLZ, Ort, Bundesland, KreisKreisfreieStadt,
  Breitengrad, Laengengrad, AnzahlLadepunkteLkw, MaxLadeleistungKW,
  InstallierteLeistungKW, Stellplatzlaenge, Durchfahrt, Inbetriebnahmedatum, ARS`
- `ARS`/AGS über denselben Spatial Join wie `update_data.py::add_ags()` —
  Funktion vorher nach `scripts/_common.py` ziehen statt kopieren.
- Plausibilitätsprüfung vor dem Schreiben (Mindest-Zeilenzahl, Pflichtspalten
  vorhanden, Koordinaten in DE-Bounding-Box); bei Fehlschlag `sys.exit(1)`,
  damit kein kaputtes Parquet committet wird.
- Neuer Workflow `.github/workflows/update_lkw_data.yml`: monatlich, aber **nicht**
  zur gleichen Uhrzeit wie `update_data.yml` (beide pushen auf `main`), z. B.
  `0 7 5 * *`. Committet nur die neue Parquet-Datei + Versionsstempel.
- Versionsstempel: `01_app/_data_version.py` um `LKW_LAST_UPDATED` erweitern.
  Achtung: der Workflow darf die Datei nicht komplett überschreiben, sonst geht
  `LAST_UPDATED` der BNetzA-Pipeline verloren -> beide Workflows müssen jeweils
  nur ihre eigene Zeile ersetzen (kleiner Helper in `scripts/_common.py`).

## Phase 2 — App
- `data_loading.py`: `load_lkw_data()` mit `@st.cache_data(ttl=3600)`, Rückgabe
  `None` bei fehlender Datei (wie `load_kba_data`); `load_all()` gibt vier Werte
  zurück -> Aufrufer in `app.py` anpassen.
- `config.py`: `LKW_HPC_THRESHOLD_KW = 350`, `MCS_THRESHOLD_KW = 1000`,
  Kategorien/Farben für die Lkw-Ansicht, Zielwerte des Initialnetzes
  (Referenzlinie: rund 350 geförderte Standorte bis 2030) als benannte Konstanten.
- Neu `01_app/sections/lkw.py::render_lkw()`, eingehängt als sechster Tab
  ("Lkw-Laden", zwischen "Landkreise" und "Daten"). Inhalt:
  - KPI-Reihe: Lkw-geeignete Standorte, Lkw-geeignete Ladepunkte, davon >= 350 kW,
    installierte Leistung, Anzahl Betreiber.
  - **Punktkarte** (folium `Marker`/`CircleMarker` + Cluster) statt Choropleth:
    bei wenigen hundert Standorten ist eine Kreis-Einfärbung irreführend.
    Tooltip: Standort, Betreiber, Anzahl Lkw-Ladepunkte, max. kW, Durchfahrt.
  - Balken je Bundesland (absolut, optional je 1.000 km Autobahn/Fläche später).
  - Zubau-Zeitreihe nur, wenn Phase 0 ein Inbetriebnahmedatum bestätigt;
    sonst Momentaufnahme + Hinweistext.
- Filter: der Tab bringt eigene, lokale Bedienelemente (Bundesland, Mindest-kW,
  nur Durchfahrt) und respektiert die Sidebar bewusst nicht — mit `st.info`-Hinweis,
  wie es der Karten-Tab schon macht. Grund: die Sidebar-Leistungskategorien
  (22/150 kW) sind Pkw-Logik und passen nicht zu Lkw-Schwellen.
- `sections/header.py`: Datenstand-Zeile um "Lkw: <Stand>" ergänzen.
- `sections/info.py`: Quelle (Mobilithek/Leitstelle, Lizenz) und zwei Limitationen
  ergänzen: (a) Erfassung beruht auf freiwilliger Datenlieferung der Betreiber
  (Stand der Berichte: 13 Betreiber), ist also nicht vollständig; (b) Depot-Laden
  auf Betriebshöfen ist gar nicht enthalten, obwohl es der Hauptanwendungsfall ist.

## Phase 3 — Optionale Ausbaustufe (eigenes Issue, nicht Teil des ersten Schritts)
- `lkw_geeignet`-Flag auf die Register-Daten joinen (nur wenn Phase 0 einen
  belastbaren Schlüssel zeigt) und als Sidebar-Filter anbieten -> alle bestehenden
  Auswertungen ließen sich damit auf Lkw-taugliche Standorte einschränken.
- KBA-Bestand für E-Nutzfahrzeuge (N2/N3) als Nachfrage-Bezug analog `lp_pro_ev`.
- Soll/Ist gegen das Initialnetz (124 unbewirtschaftete Rastanlagen aus der
  Ausschreibung 2026, Ziel rund 350 Standorte bis 2030).

## Doku
- `README.md`: vierter Datensatz, neuer Pipeline-Abschnitt, Ordnerbaum.
- `CLAUDE.md`: Layout- und Pipeline-Abschnitt um Script/Workflow/Parquet ergänzen.
- Markdown-Doku zum neuen Script (Konvention: "Every code needs a Markdown file").

## Akzeptanzkriterien
- [ ] `uv run python scripts/update_lkw_data.py` erzeugt die Parquet-Datei mit
      dokumentiertem Schema und bricht bei Teil-/Leerantwort ohne Überschreiben ab.
- [ ] Neuer Workflow läuft per `workflow_dispatch` grün und committet nur seine Datei.
- [ ] `LAST_UPDATED` und `LKW_LAST_UPDATED` überleben beide Workflows.
- [ ] `uv run streamlit run 01_app/app.py`: neuer Tab mit plausiblen Zahlen; die
      fünf bestehenden Tabs unverändert; App startet auch ohne die neue Datei.
- [ ] Quelle und Lizenz in "Hinweise" genannt; README/CLAUDE.md aktualisiert.

## Aufwand / Risiken
- Aufwand: Phase 0 ca. 2-3 h, Phase 1 ca. 3-4 h, Phase 2 ca. 4-6 h, Doku ca. 1 h.
- Komplexität: mittel. Hauptrisiko: Zugriffsweg/Lizenz des Datenangebots (Phase 0).
- Zweites Risiko: Datenqualität/Vollständigkeit — die Lkw-Zahlen sind deutlich
  kleiner und volatiler als der Pkw-Bestand, deshalb Hinweistexte statt
  scheinbar exakter Kennzahlen.
