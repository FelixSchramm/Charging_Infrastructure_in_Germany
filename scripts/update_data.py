import re
import requests
import pandas as pd
import geopandas as gpd
from io import BytesIO
from pathlib import Path

DOWNLOAD_PAGE = "https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/DownloadundKontakt.html"
SHAPEFILE = Path("02_data/02_meta_data/vg250_01-01.gk3.shape.ebenen/vg250_ebenen_0101/VG250_KRS.shp")
OUT_PATH = Path("02_data/03_computed_data/combined_ladestation_ladepunkt.parquet")
VERSION_PATH = Path("01_app/_data_version.py")


def get_xlsx_url() -> str:
    html = requests.get(DOWNLOAD_PAGE, timeout=30).text
    match = re.search(
        r'https://data\.bundesnetzagentur\.de/[^\s"\'<>]+Ladesaeulenregister[^\s"\'<>]+\.xlsx',
        html,
    )
    if not match:
        raise RuntimeError("XLSX-Download-Link auf BNetzA-Seite nicht gefunden")
    return match.group(0)


def _to_float(val) -> float:
    if pd.isna(val):
        return float("nan")
    s = str(val).replace(",", ".")
    if ";" in s:
        parts = [p.strip() for p in s.split(";") if p.strip()]
        return max(float(p) for p in parts)
    return float(s)


def download_and_parse(url: str) -> pd.DataFrame:
    print(f"Lade XLSX von: {url}")
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    df = pd.read_excel(
        BytesIO(r.content),
        sheet_name="Ladesäulenregister",
        skiprows=10,
        engine="openpyxl",
        dtype=str,
    )
    print(f"  → {len(df)} Stationen, {len(df.columns)} Spalten")
    return df


def transform(df_raw: pd.DataFrame) -> pd.DataFrame:
    df_raw["Breitengrad"] = df_raw["Breitengrad"].apply(_to_float)
    df_raw["Längengrad"] = df_raw["Längengrad"].apply(_to_float)
    df_raw["Nennleistung Ladeeinrichtung [kW]"] = df_raw[
        "Nennleistung Ladeeinrichtung [kW]"
    ].apply(_to_float)

    station_cols = [
        "Ladeeinrichtungs-ID",
        "Betreiber",
        "Straße",
        "Hausnummer",
        "Adresszusatz",
        "Postleitzahl",
        "Ort",
        "Bundesland",
        "Kreis/kreisfreie Stadt",
        "Breitengrad",
        "Längengrad",
        "Inbetriebnahmedatum",
        "Nennleistung Ladeeinrichtung [kW]",
        "Art der Ladeeinrichtung",
        "Anzahl Ladepunkte",
    ]

    frames = []
    for i in range(1, 7):
        typ_col = f"Steckertypen{i}"
        kw_col = f"Nennleistung Stecker{i}"
        if typ_col not in df_raw.columns:
            break
        slot = df_raw[station_cols + [typ_col, kw_col]].copy()
        slot = slot.rename(columns={typ_col: "Steckertyp", kw_col: "LadeleistungInKW"})
        slot["LadeleistungInKW"] = slot["LadeleistungInKW"].apply(_to_float)
        slot = slot.dropna(subset=["Steckertyp", "LadeleistungInKW"])
        frames.append(slot)

    df = pd.concat(frames, ignore_index=True)
    print(f"  → {len(df)} Ladepunkte nach Melt")

    df = df.rename(
        columns={
            "Ladeeinrichtungs-ID": "ladestation_id",
            "Straße": "Strasse",
            "Postleitzahl": "PLZ",
            "Kreis/kreisfreie Stadt": "KreisKreisfreieStadt",
            "Längengrad": "Laengengrad",
            "Nennleistung Ladeeinrichtung [kW]": "InstallierteLadeleistungNLL",
            "Art der Ladeeinrichtung": "ArtLadeeinrichtung",
            "Anzahl Ladepunkte": "AnzahlLadepunkteBNetzA",
        }
    )

    df["BetreiberBereinigt"] = df["Betreiber"]
    df["NennleistungBNetzA"] = df["InstallierteLadeleistungNLL"]
    df["LadeUseCase"] = "Unbekannt"
    df["ladepunkt_id"] = range(1, len(df) + 1)
    df["Inbetriebnahmedatum"] = pd.to_datetime(df["Inbetriebnahmedatum"], errors="coerce")

    return df


def add_ags(df: pd.DataFrame) -> pd.DataFrame:
    if not SHAPEFILE.exists():
        print("  Warnung: Shapefile nicht gefunden, AGS wird übersprungen")
        df["ARS"] = None
        return df

    mask = df["Breitengrad"].notna() & df["Laengengrad"].notna()
    gdf = gpd.GeoDataFrame(
        df[mask].copy(),
        geometry=gpd.points_from_xy(df.loc[mask, "Laengengrad"], df.loc[mask, "Breitengrad"]),
        crs="EPSG:4326",
    )

    districts = gpd.read_file(SHAPEFILE)[["AGS", "geometry"]].to_crs("EPSG:4326")
    joined = gpd.sjoin(gdf, districts, how="left", predicate="within")

    df["ARS"] = None
    df.loc[mask, "ARS"] = joined["AGS"].values
    return df


def save_output(df: pd.DataFrame, datenstand: str | None) -> None:
    """Schreibt das Parquet nach OUT_PATH und den Datenstand nach VERSION_PATH.

    Wird auch von update_data_official.py genutzt, damit beide Pipelines
    identisch schreiben.

    :param df: fertiger Ladepunkt-DataFrame
    :param datenstand: Datum als "YYYY-MM-DD", oder None wenn nicht ermittelbar
    """
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Gespeichert: {OUT_PATH} ({OUT_PATH.stat().st_size / 1e6:.1f} MB)")
    print(
        f"Fertig: {len(df)} Ladepunkte aus {df['ladestation_id'].nunique()} Stationen"
    )

    if datenstand:
        VERSION_PATH.write_text(f'LAST_UPDATED = "{datenstand}"\n')
        print(f"Datenstand: {datenstand} -> {VERSION_PATH}")
    else:
        print("Warnung: kein Datenstand ermittelt, _data_version.py unverändert")


def main():
    print("Suche aktuelle Download-URL...")
    url = get_xlsx_url()

    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", url)
    datenstand = date_match.group(1) if date_match else None

    print("Lade und parse XLSX...")
    df_raw = download_and_parse(url)

    print("Transformiere in Ladepunkt-Format...")
    df = transform(df_raw)

    print("Räumliche Zuordnung AGS via Shapefile...")
    df = add_ags(df)

    save_output(df, datenstand)


if __name__ == "__main__":
    main()
