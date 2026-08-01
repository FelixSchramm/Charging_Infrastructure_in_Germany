"""Fetch BNetzA's official daily charging-station export and rebuild the parquet.

1. REST GET & idempotency
   A GET request is defined by the HTTP spec to be "safe": it must not change any
   state on the server. That is what makes this whole script, and the live probe
   used to calibrate it (Step 0 of the implementation plan), harmless to re-run as
   often as needed while developing or debugging -- there is no "used up" quota of
   exports, no order being placed, no record being created. Every call just asks
   "what does the current export look like" and gets the same answer back until
   BNetzA publishes a new one. This is different from POST/PUT/DELETE, where
   re-running a failed script blindly could duplicate or corrupt data server-side.

2. The envelope/response-wrapper pattern
   The API does not return a bare JSON array of stations. It wraps the payload in
   an object alongside metadata: `{"documentDate": ..., "documentTime": ...,
   "chargingStations": [...]}`. This is the "envelope" (or "response wrapper")
   pattern: metadata that describes the payload -- here, when the snapshot was
   generated -- travels with the payload instead of being inferred separately
   (e.g. from an HTTP header or a separate request). It is common across many
   public data APIs and worth recognizing by name, because it always means "unwrap
   one level before you get to the records."

3. Nested-to-tabular flattening (ETL)
   The export is a tree: Station -> Evse -> Connector, one-to-many at each level.
   The dashboard, however, needs a flat table with one row per connector (a
   station can offer several plug types across several physical charge points).
   Turning a tree into a flat table is a standard ETL step usually called
   "flattening" or "normalization". `update_data.py`'s old `transform()` faced the
   same underlying problem in a different shape: the XLSX had wide columns
   `Steckertypen1..6` (one station row, up to six plug slots side by side) and
   melted them into one row per plug. Here the shape is a nested tree instead of
   wide columns, but the goal is identical: one row per connector.

4. Defensive validation before persisting
   External data can be malformed, truncated, or -- worse -- silently wrong (e.g.
   a station count that has collapsed because of an upstream bug) without the HTTP
   request itself failing. "Trust but verify" means the freshly fetched data is
   checked against sanity thresholds and against the last known-good file before
   it is allowed to replace that file. Crucially, this check must happen *before*
   the write, not after: once `to_parquet()` has overwritten the old file, the
   last known-good state is gone, and a subsequent check could only detect
   corruption, not prevent it.

5. No pagination here
   The OpenAPI spec defines no offset/limit/cursor query parameters for this
   endpoint, and the live probe in Step 0 confirmed it in practice: a single
   request returned all 115,613 stations in one response. So this script does not
   page through results. Worth re-checking if the dataset grows substantially in
   the future -- APIs sometimes introduce pagination as a minor, non-breaking
   change (e.g. an optional `page` parameter with a default that still returns
   everything today), and a script written to assume "always exactly one request"
   would then silently start missing data instead of failing loudly.
"""

import sys
import time

import pandas as pd
import requests

from update_data import add_ags, OUT_PATH, SHAPEFILE, VERSION_PATH

API_URL = "https://ladesaeulenregister.bnetza.de/els/service/public/v1/chargepoints"

# Live probe on 2026-08-01: 116.3 MB, fetched in ~52 s (2.2 MB/s). 120 s leaves
# roughly 2x headroom over the observed time for slower connections (e.g. a
# GitHub Actions runner on a bad day), similar in spirit to update_data.py's
# generous timeout=300 for its (smaller) XLSX download.
REQUEST_TIMEOUT = 120
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5  # linear backoff between attempts

# Live probe on 2026-08-01 observed 115,613 stations. The threshold below is set
# well under that (~87 %) rather than close to it: normal day-to-day fluctuation
# (a few hundred stations added/removed) must not trip this guard, but a
# genuinely broken export (empty, truncated, wrong endpoint) still will. This is
# a hard floor, independent of whatever the previous run's count happened to be
# -- see PLAUSIBILITY_MIN_RATIO below for the relative check against that.
MIN_RECORDS = 100_000
PLAUSIBILITY_MIN_RATIO = (
    0.9  # new station count must be >= 90% of the last known-good file's
)

REQUIRED_COLUMNS = [
    "ladestation_id",
    "Betreiber",
    "Strasse",
    "Hausnummer",
    "Adresszusatz",
    "PLZ",
    "Ort",
    "Bundesland",
    "KreisKreisfreieStadt",
    "Breitengrad",
    "Laengengrad",
    "Inbetriebnahmedatum",
    "InstallierteLadeleistungNLL",
    "ArtLadeeinrichtung",
    "AnzahlLadepunkteBNetzA",
    "Steckertyp",
    "LadeleistungInKW",
    "ladepunkt_id",
    "BetreiberBereinigt",
    "NennleistungBNetzA",
    "LadeUseCase",
]


class ExportNotReadyError(RuntimeError):
    """Raised on HTTP 404: BNetzA has not published today's export yet."""


def fetch_export() -> dict:
    """Fetch the current export from the official BNetzA API, with retries.

    A 404 and a 500 are handled differently on purpose. A 404 means "the export
    for today does not exist yet" per the spec -- it is not a fault, and it will
    not resolve itself within the next few seconds, so retrying it just wastes
    time and delays the failure. A 500 or a network error, by contrast, can be a
    transient blip (a momentary server hiccup, a dropped connection), so those go
    through the retry loop with a short linear backoff before giving up.

    :return: parsed ExportResponse dict (documentDate, documentTime, chargingStations)
    :raises ExportNotReadyError: on HTTP 404
    :raises requests.HTTPError: on HTTP 500 after exhausting retries
    :raises requests.RequestException: on network failure after exhausting retries
    """
    headers = {
        "Accept": "application/json"
    }  # content negotiation: spec also allows XML
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(API_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                # not transient -- retrying today will not make the export appear,
                # so this raises immediately instead of going through the loop below
                raise ExportNotReadyError(
                    "BNetzA hat den heutigen Export noch nicht bereitgestellt (HTTP 404)"
                )
            response.raise_for_status()
            return response.json()
        except ExportNotReadyError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            print(
                f"Versuch {attempt}/{MAX_RETRIES} fehlgeschlagen: {exc}",
                file=sys.stderr,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)

    raise last_error


def build_target(data: dict) -> pd.DataFrame:
    """Flatten the nested Station -> Evse -> Connector export into one row per connector.

    This mirrors what `update_data.transform()` did with the old wide XLSX melt
    (`Steckertypen1..6` -> one row per plug), but the source shape here is a
    nested tree rather than wide columns, so it needs its own flattening logic
    instead of reusing `transform()`.

    :param data: parsed ExportResponse dict, as returned by fetch_export()
    :return: DataFrame, one row per connector, columns per REQUIRED_COLUMNS
    """
    # unwrap the envelope described in the module docstring's paragraph 2 --
    # the records live one level down, under "chargingStations"
    stations = data["chargingStations"]

    rows = []
    for station in stations:
        evses = station.get("evses", [])
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
            # an Evse ("Ladepunkt" per the spec) is the physical charge point; it can
            # carry several Connectors (plug variants). AnzahlLadepunkteBNetzA counts
            # evses -- it is NOT the row count produced below, since one evse with two
            # connectors yields two rows here but is still a single Ladepunkt
            "AnzahlLadepunkteBNetzA": len(evses),
        }
        for idx, evse in enumerate(evses):
            # evse_id is null for ~70% of evses in the live export (verified against
            # the real data, not assumed from the spec) -- fall back to a position
            # scoped to this station so ladepunkt_id stays unique and reasonably
            # stable across daily runs, without relying on one dataset-wide counter
            # that would shift whenever any row anywhere gets reordered
            evse_key = evse.get("evse_id") or f"{station['id']}-{idx}"
            for connector in evse.get("connectors", []):
                rows.append(
                    {
                        **base,
                        "Steckertyp": connector.get("connector_type"),
                        "LadeleistungInKW": connector.get(
                            "max_electric_power_connector"
                        ),
                        "ladepunkt_id": f"{evse_key}#{connector.get('connector_type', '')}",
                    }
                )

    df = pd.DataFrame(rows)
    df["Inbetriebnahmedatum"] = pd.to_datetime(
        df["Inbetriebnahmedatum"], format="%d.%m.%Y", errors="coerce"
    )
    df["BetreiberBereinigt"] = df["Betreiber"]
    df["NennleistungBNetzA"] = df["InstallierteLadeleistungNLL"]
    df["LadeUseCase"] = "Unbekannt"

    return df[REQUIRED_COLUMNS]


def validate(df: pd.DataFrame, df_previous: pd.DataFrame | None) -> None:
    """Check the freshly built DataFrame before it is allowed to overwrite OUT_PATH.

    A station-count regression is a hard failure because it has no legitimate
    explanation -- BNetzA's register only grows or holds steady, so a sudden drop
    almost certainly means a broken or partial export. A stale max
    Inbetriebnahmedatum, on the other hand, is only a warning: it is entirely
    normal for no new station to have gone live since yesterday, so that signal
    alone is too noisy to justify aborting the run.

    :param df: output of build_target()
    :param df_previous: previously-saved parquet (read from OUT_PATH before it
        gets overwritten), or None if OUT_PATH doesn't exist yet
    :raises ValueError: on any hard-failure condition
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Fehlende Pflichtspalten: {missing}")

    station_count = df["ladestation_id"].nunique()
    if station_count < MIN_RECORDS:
        raise ValueError(
            f"Nur {station_count} Stationen im Export, erwartet mindestens {MIN_RECORDS} "
            "-- moeglicherweise unvollstaendiger oder fehlerhafter Export"
        )

    if df_previous is not None:
        previous_count = df_previous["ladestation_id"].nunique()
        min_allowed = PLAUSIBILITY_MIN_RATIO * previous_count
        if station_count < min_allowed:
            raise ValueError(
                f"Stationszahl eingebrochen: {station_count} neu vs. {previous_count} zuvor "
                f"(unter {PLAUSIBILITY_MIN_RATIO:.0%} des letzten bekannten Standes) "
                "-- Abbruch, um keine kaputten Daten zu speichern"
            )

        # asymmetric on purpose: a stale date is expected sometimes (see docstring
        # above), a count crash never is -- so only the count crash raises
        if df["Inbetriebnahmedatum"].max() < df_previous["Inbetriebnahmedatum"].max():
            print(
                "Warnung: neuestes Inbetriebnahmedatum ist aelter als im letzten Stand "
                f"({df['Inbetriebnahmedatum'].max()} < "
                f"{df_previous['Inbetriebnahmedatum'].max()})"
            )


def main() -> None:
    """Orchestrate fetch -> validate -> add_ags -> save.

    In that order, so a bad export is rejected before the comparatively expensive
    spatial join (add_ags) ever runs against data that is about to be discarded
    anyway.
    """
    print(f"Rufe Export von {API_URL} ab...")
    data = fetch_export()
    print(
        f"  -> Datenstand {data['documentDate']} {data['documentTime']}, "
        f"{len(data['chargingStations'])} Stationen im Rohexport"
    )

    print("Baue Ziel-Schema (eine Zeile pro Connector)...")
    df = build_target(data)
    print(f"  -> {len(df)} Ladepunkte aus {df['ladestation_id'].nunique()} Stationen")

    # read the previous known-good file BEFORE it gets overwritten further down --
    # reordering this after the to_parquet() write would silently defeat validate()'s
    # comparison against the last known-good state
    df_previous = pd.read_parquet(OUT_PATH) if OUT_PATH.exists() else None

    print("Validiere gegen Pflichtspalten und letzten bekannten Stand...")
    validate(df, df_previous)

    print(f"Raeumliche Zuordnung AGS via Shapefile ({SHAPEFILE})...")
    df = add_ags(df)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Gespeichert: {OUT_PATH} ({OUT_PATH.stat().st_size / 1e6:.1f} MB)")

    # documentDate arrives as "dd.MM.yyyy"; VERSION_PATH expects "YYYY-MM-DD" --
    # a single inline conversion, not worth its own function for one use site
    day, month, year = data["documentDate"].split(".")
    datenstand = f"{year}-{month}-{day}"
    VERSION_PATH.write_text(f'LAST_UPDATED = "{datenstand}"\n')
    print(f"Datenstand: {datenstand} -> {VERSION_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # last line of defense for a cron entrypoint: any failure must exit
        # non-zero so the calling GitHub Actions step fails and the git-commit
        # step never runs, instead of silently overwriting last month's good data
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)
