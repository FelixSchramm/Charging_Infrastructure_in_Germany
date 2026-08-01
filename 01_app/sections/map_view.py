"""Regionale Analyse: Choropleth-Karte des Bestands je Kreis."""

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from config import (
    KAT_HPC,
    KAT_NORMAL,
    KAT_SCHNELL,
    MAP_BOUNDS,
    MAP_CENTER,
    MAP_ZOOM,
    NOW_DUNKELBLAU,
    NOW_GRAU,
)
from filters import Filters, apply_filters_for_map

# Spalten, die nach dem Merge vorhanden sein müssen, und Karten-Datensätze.
_LADE_COLS = ["HPC", "Schnellladen", "Normalladen"]
_TOOLTIP_STYLE = f"""
    background-color: white;
    border: 2px solid {NOW_DUNKELBLAU};
    border-radius: 6px;
    box-shadow: 3px 3px 6px rgba(0,0,0,0.2);
    font-size: 13px;
    padding: 8px;
"""


def render_map(df: pd.DataFrame, gdf_districts, df_kba, f: Filters):
    """Zeichnet die Choropleth-Karte (gesamtdeutsch, alle Filter außer Bundesland)."""
    st.header("Regionale Analyse")
    st.caption("Bestand öffentlicher Ladepunkte je Kreis (gesamtdeutsch).")

    if gdf_districts is None:
        st.warning(
            "Geodaten (Shapefile) konnten nicht geladen werden. Die Karte wird nicht angezeigt."
        )
        return

    df_for_map = apply_filters_for_map(df, f)
    df_for_map = df_for_map.assign(AGS=df_for_map["ARS"].astype(str).str.zfill(5))

    gdf_for_map = _build_map_geodata(df_for_map, gdf_districts, df_kba)

    m = folium.Map(
        location=MAP_CENTER,
        tiles="CartoDB positron",
        zoom_start=MAP_ZOOM,
        min_zoom=MAP_ZOOM,
        max_bounds=True,
    )
    m.fit_bounds(MAP_BOUNDS)

    use_ev_metric = df_kba is not None and gdf_for_map["lp_pro_ev"].notna().any()
    choropleth_col, legend_name, bins = _choropleth_config(gdf_for_map, use_ev_metric)

    gdf_choropleth = gdf_for_map.copy()
    if use_ev_metric:
        gdf_choropleth["lp_pro_ev"] = gdf_choropleth["lp_pro_ev"].fillna(0)

    folium.Choropleth(
        geo_data=gdf_choropleth,
        data=gdf_choropleth,
        columns=["AGS", choropleth_col],
        key_on="feature.properties.AGS",
        fill_color="Greens",
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name=legend_name,
        highlight=True,
        bins=bins,
        nan_fill_color=NOW_GRAU,
        nan_fill_opacity=0.4,
    ).add_to(m)

    _add_tooltip_layer(m, gdf_for_map, use_ev_metric)

    st_folium(m, use_container_width=True, height=600)

    st.info(
        "Der **Bundesland-Filter** wirkt auf dieser Karte nicht – sie zeigt immer "
        "ganz Deutschland. Die übrigen Filter (Zeitraum, Leistungstyp, Landkreis, "
        "Betreiber) werden dagegen angewendet.",
        icon="ℹ️",
    )


def _build_map_geodata(
    df_for_map: pd.DataFrame, gdf_districts, df_kba
) -> gpd.GeoDataFrame:
    """Aggregiert Ladepunkte je Kreis und merged sie mit Geometrie + KBA-Bestand."""
    agg = (
        df_for_map.groupby(["AGS", "Leistungskategorie"])
        .size()
        .unstack(fill_value=0)
        .rename(
            columns={
                KAT_HPC: "HPC",
                KAT_SCHNELL: "Schnellladen",
                KAT_NORMAL: "Normalladen",
            }
        )
    )
    for col_name in _LADE_COLS:
        if col_name not in agg.columns:
            agg[col_name] = 0
    agg["Gesamt"] = agg[_LADE_COLS].sum(axis=1)
    district_data = agg.reset_index()

    merged = gdf_districts.merge(district_data, on="AGS", how="left")
    for col_name in ["Gesamt", *_LADE_COLS]:
        merged[col_name] = merged[col_name].fillna(0).astype(int)

    if df_kba is not None:
        merged = merged.merge(
            df_kba[["AGS", "bev_bestand", "phev_bestand"]], on="AGS", how="left"
        )
        merged["bev_bestand"] = merged["bev_bestand"].fillna(0).astype(int)
        merged["phev_bestand"] = merged["phev_bestand"].fillna(0).astype(int)
        merged["gewichteter_bestand"] = (
            merged["bev_bestand"] + 0.5 * merged["phev_bestand"]
        )
        merged["lp_pro_ev"] = (
            merged["Gesamt"] / merged["gewichteter_bestand"].replace(0, float("nan"))
        ).round(4)
    else:
        merged["bev_bestand"] = 0
        merged["phev_bestand"] = 0
        merged["gewichteter_bestand"] = float("nan")
        merged["lp_pro_ev"] = float("nan")

    return merged[
        [
            "AGS",
            "GEN",
            "geometry",
            "Gesamt",
            "HPC",
            "Schnellladen",
            "Normalladen",
            "bev_bestand",
            "phev_bestand",
            "lp_pro_ev",
        ]
    ]


def _choropleth_config(gdf_for_map: gpd.GeoDataFrame, use_ev_metric: bool):
    """Bestimmt Spalte, Legendentitel und Klassengrenzen (bins) der Einfärbung."""
    if use_ev_metric:
        valid_vals = gdf_for_map["lp_pro_ev"].dropna()
        true_max = float(valid_vals.max()) if len(valid_vals) > 0 else 0.2
        bin_candidates = [0.01, 0.02, 0.05, 0.08, 0.12, 0.2, 0.35]
        bins = sorted(
            set(
                [0.0]
                + [b for b in bin_candidates if 0 < b < true_max]
                + [round(true_max * 1.001, 6)]
            )
        )
        if len(bins) < 4:
            bins = [
                0.0,
                round(true_max / 3, 6),
                round(true_max * 2 / 3, 6),
                round(true_max * 1.001, 6),
            ]
        return (
            "lp_pro_ev",
            "Ladepunkte je gewichtetem EV-Bestand (BEV=1, PHEV=0,5)",
            bins,
        )

    max_val = int(gdf_for_map["Gesamt"].max()) if len(gdf_for_map) > 0 else 0
    bins = sorted(
        set(
            [0] + [b for b in [100, 500, 1000, 2500] if 0 < b < max_val] + [max_val + 1]
        )
    )
    if len(bins) < 4:
        extras = [i for i in range(1, 10) if i not in bins][: 4 - len(bins)]
        bins = sorted(set(bins + extras))
    return "Gesamt", "Anzahl Ladepunkte pro Kreis", bins


def _add_tooltip_layer(
    m: folium.Map, gdf_for_map: gpd.GeoDataFrame, use_ev_metric: bool
):
    """Legt eine transparente GeoJSON-Ebene mit Hover-Tooltip über die Karte."""
    fields = ["GEN", "Gesamt", "HPC", "Schnellladen", "Normalladen"]
    aliases = [
        "Kreis:",
        "Ladepunkte gesamt:",
        "HPC (>= 150 kW):",
        "Schnellladen (> 22 kW):",
        "Normalladen (<= 22 kW):",
    ]
    if use_ev_metric:
        fields += ["bev_bestand", "phev_bestand", "lp_pro_ev"]
        aliases += ["BEV-Bestand:", "PHEV-Bestand:", "LP je gew. EV-Bestand:"]

    folium.GeoJson(
        gdf_for_map,
        style_function=lambda x: {
            "fillColor": "transparent",
            "color": "transparent",
            "weight": 0,
        },
        highlight_function=lambda x: {
            "weight": 2,
            "color": NOW_DUNKELBLAU,
            "fillOpacity": 0.1,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=fields, aliases=aliases, sticky=True, style=_TOOLTIP_STYLE
        ),
    ).add_to(m)
