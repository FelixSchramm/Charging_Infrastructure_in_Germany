"""Fetch BNetzA's official daily charging-station export and rebuild the parquet.

Alternative to update_data.py, which parses the monthly XLSX register. Same
output paths and schema, different source. See update_data_official.md next to
this file for the design background, the full field mapping and the reasoning
behind the thresholds below.

The endpoint returns the complete dataset in a single response -- the OpenAPI
spec defines no offset/limit/cursor parameters. Re-check if the dataset grows
substantially: an added optional page parameter would make this script silently
miss data instead of failing loudly.
"""

import sys
import time

import pandas as pd
import requests

from update_data import add_ags, save_output, OUT_PATH, SHAPEFILE

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

# new station count must be >= 90% of the last known-good file's
PLAUSIBILITY_MIN_RATIO = 0.9

# a wrong date format would turn every value into NaT via errors="coerce" and
# silently empty the dashboard's year dimension, so guard the share of NaT
MAX_NAT_RATIO = 0.5

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
    # content negotiation: the spec also allows XML
    headers = {"Accept": "application/json"}
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(API_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                # ExportNotReadyError is a RuntimeError, so it passes the
                # RequestException handler below untouched and aborts the loop
                raise ExportNotReadyError(
                    "BNetzA hat den heutigen Export noch nicht bereitgestellt (HTTP 404)"
                )
            response.raise_for_status()
            return response.json()
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
        # id, operator and coordinates are indexed directly rather than via .get():
        # they are mandatory per spec and present in 100% of the live export, so a
        # missing one means the payload changed and should fail loudly here
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
            # kW, not W -- the app sums this into GW (kpis.py) and compares the
            # connector value against HPC_THRESHOLD_KW, verified against live data
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

    Missing columns need no check here: build_target() ends with
    df[REQUIRED_COLUMNS], so a missing one already raises a KeyError there.

    :param df: output of build_target()
    :param df_previous: previously-saved parquet (read from OUT_PATH before it
        gets overwritten), or None if OUT_PATH doesn't exist yet
    :raises ValueError: on any hard-failure condition
    """
    station_count = df["ladestation_id"].nunique()
    if station_count < MIN_RECORDS:
        raise ValueError(
            f"Nur {station_count} Stationen im Export, erwartet mindestens {MIN_RECORDS} "
            "-- moeglicherweise unvollstaendiger oder fehlerhafter Export"
        )

    nat_ratio = df["Inbetriebnahmedatum"].isna().mean()
    if nat_ratio > MAX_NAT_RATIO:
        raise ValueError(
            f"{nat_ratio:.0%} der Inbetriebnahmedaten sind leer "
            f"(erlaubt bis {MAX_NAT_RATIO:.0%}) -- vermutlich hat sich das "
            "Datumsformat der API geaendert"
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

    # must stay ahead of save_output() below -- afterwards the last known-good
    # state is gone and validate() has nothing left to compare against
    df_previous = pd.read_parquet(OUT_PATH) if OUT_PATH.exists() else None

    print("Validiere gegen letzten bekannten Stand...")
    validate(df, df_previous)

    print(f"Raeumliche Zuordnung AGS via Shapefile ({SHAPEFILE})...")
    df = add_ags(df)

    # documentDate arrives as "dd.MM.yyyy", save_output expects "YYYY-MM-DD"
    day, month, year = data["documentDate"].split(".")
    save_output(df, f"{year}-{month}-{day}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # last line of defense for a cron entrypoint: any failure must exit
        # non-zero so the calling GitHub Actions step fails and the git-commit
        # step never runs, instead of silently overwriting last month's good data
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)
