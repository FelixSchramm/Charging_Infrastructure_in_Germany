import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import plotly.express as px
from pathlib import Path

# --- SEITENKONFIGURATION & FARBPALETTE ---
st.set_page_config(
    page_title="Dashboard Ladeinfrastruktur | NOW GmbH",
    page_icon="⚡",
    layout="wide"
)

# NOW GmbH Farbpalette
NOW_GRUEN = "#00B092"
NOW_DUNKELBLAU = "#003247"
NOW_HELLBLAU = "#88C5D9"
NOW_GRAU = "#D3D3D3"

# --- DATEN LADEN & VORBEREITEN ---
@st.cache_data
def load_data():
    try:
        # --- KORRIGIERTER PFAD ZUM DATENSATZ ---
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        csv_path = project_root / "02_data/03_computed_data/combined_ladestation_ladepunkt.csv"
        
        df = pd.read_csv(csv_path, low_memory=False, dtype={'ARS': str})
        df['Inbetriebnahmedatum'] = pd.to_datetime(df['Inbetriebnahmedatum'], errors='coerce')
        df['Jahr'] = df['Inbetriebnahmedatum'].dt.year
        df.dropna(subset=['Inbetriebnahmedatum', 'Bundesland', 'KreisKreisfreieStadt', 'ARS'], inplace=True)
        
        def get_leistungskategorie(leistung):
            if leistung >= 150: return 'HPC-Laden (>= 150 kW)'
            elif leistung > 22: return 'Schnellladen (> 22 kW)'
            else: return 'Normalladen (<= 22 kW)'
        df['Leistungskategorie'] = df['LadeleistungInKW'].apply(get_leistungskategorie)
        
        try:
            shapefile_path = project_root / "02_data/02_meta_data/vg250_01-01.gk3.shape.ebenen/vg250_ebenen_0101/VG250_KRS.shp"
            gdf_districts = gpd.read_file(shapefile_path)
        except Exception:
             st.warning("Shapefile nicht gefunden. Die Karte wird nicht angezeigt.")
             gdf_districts = None

        return df, gdf_districts
        
    except FileNotFoundError:
        st.error("FEHLER: Die Datendatei wurde nicht im erwarteten Pfad '02_data/03_computed_data/' gefunden.")
        return None, None

df, gdf_districts = load_data()

if df is not None:
    # --- SIDEBAR & FILTER (DEINE GEWÜNSCHTE ANORDNUNG) ---
    st.sidebar.header("Filteroptionen")

    # 1. Jahr-Filter
    min_jahr, max_jahr = int(df['Jahr'].min()), int(df['Jahr'].max())
    selected_jahre = st.sidebar.slider("Zeitraum (Jahr):", min_value=min_jahr, max_value=max_jahr, value=(min_jahr, max_jahr))
    
    # 2. Bundesland-Filter
    bundeslaender = sorted(df['Bundesland'].unique())
    selected_bundeslaender = st.sidebar.multiselect("Bundesland:", options=bundeslaender, default=bundeslaender)

    # 3. Text-Suchfeld für Landkreis/Stadt
    search_kreis = st.sidebar.text_input("Landkreis/Stadt (Suche):")

    # 4. Text-Suchfeld für Betreiber
    search_betreiber = st.sidebar.text_input("Betreiber (Suche):")
    
    # 5. Leistungstyp-Filter
    leistungstypen = sorted(df['Leistungskategorie'].unique())
    selected_leistungstypen = st.sidebar.multiselect("Leistungstyp:", options=leistungstypen, default=leistungstypen)

    # 6. Anwendungsfall-Filter
    use_cases = sorted(df['LadeUseCase'].dropna().unique())
    selected_use_cases = st.sidebar.multiselect("Anwendungsfall:", options=use_cases, default=use_cases)

    # --- DATENFILTERUNG ---
    df_filtered = df[
        (df['Jahr'] >= selected_jahre[0]) &
        (df['Jahr'] <= selected_jahre[1]) &
        df['Bundesland'].isin(selected_bundeslaender) &
        df['Leistungskategorie'].isin(selected_leistungstypen) &
        df['LadeUseCase'].isin(selected_use_cases)
    ]
    if search_kreis:
        df_filtered = df_filtered[df_filtered['KreisKreisfreieStadt'].str.contains(search_kreis, case=False, na=False)]
    if search_betreiber:
        df_filtered = df_filtered[df_filtered['BetreiberBereinigt'].str.contains(search_betreiber, case=False, na=False)]
    df_filtered = df_filtered.copy()

    # --- HAUPTSEITE ---
    st.title("⚡ Dashboard Ladeinfrastruktur Deutschland")
    st.markdown("Eine interaktive Analyse für die **NOW GmbH**.")

    # KPIs
    st.header("Statistische Kennzahlen (KPIs)")
    num_ladestationen = df_filtered['ladestation_id'].nunique()
    num_ladepunkte = len(df_filtered)
    leistung_ladepunkt_gw = df_filtered['LadeleistungInKW'].sum() / 1_000_000
    df_stationen_filtered = df_filtered.drop_duplicates(subset='ladestation_id')
    leistung_station_gw = df_stationen_filtered.get('InstallierteLadeleistungNLL', 0).sum() / 1_000_000
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Anzahl Ladestationen", f"{num_ladestationen:,}".replace(',', '.'))
    col2.metric("Anzahl Ladepunkte", f"{num_ladepunkte:,}".replace(',', '.'))
    col3.metric("Leistung nach Ladepunkt", f"{leistung_ladepunkt_gw:.2f} GW")
    col4.metric("Leistung nach Ladesäule", f"{leistung_station_gw:.2f} GW")
    st.divider()

    # ZEITREIHEN
    st.header("Entwicklung über die Zeit")
    col_ts1, col_ts2 = st.columns(2)
    with col_ts1:
        zubau_punkte = df_filtered.groupby('Jahr').size().reset_index(name='Anzahl')
        fig_zubau_punkte = px.bar(zubau_punkte, x='Jahr', y='Anzahl', title='<b>Jährlicher Zubau von Ladepunkten</b>')
        fig_zubau_punkte.update_traces(marker_color=NOW_GRUEN)
        st.plotly_chart(fig_zubau_punkte, use_container_width=True)
    with col_ts2:
        zubau_stationen = df_stationen_filtered.groupby('Jahr').size().reset_index(name='Anzahl')
        fig_zubau_stationen = px.bar(zubau_stationen, x='Jahr', y='Anzahl', title='<b>Jährlicher Zubau von Ladestationen</b>')
        fig_zubau_stationen.update_traces(marker_color=NOW_DUNKELBLAU)
        st.plotly_chart(fig_zubau_stationen, use_container_width=True)
    st.divider()
    
    # DETAILLIERTE ANALYSEN
    st.header("Detaillierte Analysen")
    col_detail1, col_detail2 = st.columns(2)
    with col_detail1:
        kategorie_counts = df_filtered['Leistungskategorie'].value_counts().reset_index()
        color_map_pie = {'HPC-Laden (>= 150 kW)': NOW_GRUEN, 'Schnellladen (> 22 kW)': NOW_DUNKELBLAU, 'Normalladen (<= 22 kW)': NOW_GRAU}
        fig_kategorien = px.pie(kategorie_counts, names='Leistungskategorie', values='count', title='<b>Anteil der Ladepunkttypen</b>', color='Leistungskategorie', color_discrete_map=color_map_pie)
        st.plotly_chart(fig_kategorien, use_container_width=True)
    with col_detail2:
        top_10_betreiber = df_filtered['BetreiberBereinigt'].value_counts().nlargest(10).reset_index()
        fig_betreiber = px.bar(top_10_betreiber, x='count', y='BetreiberBereinigt', orientation='h', title='<b>Top 10 Betreiber</b>', labels={'count': 'Anzahl Ladepunkte', 'BetreiberBereinigt': 'Betreiber'}, color_discrete_sequence=[NOW_GRUEN])
        fig_betreiber.update_layout(yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig_betreiber, use_container_width=True)
    st.divider()

    # REGIONALE ANALYSE & KARTE
    st.header("Regionale Analyse")
    if gdf_districts is not None and not df_filtered.empty:
        charging_points_per_district = df_filtered.groupby('ARS')['ladepunkt_id'].count().reset_index()
        charging_points_per_district.rename(columns={'ladepunkt_id': 'num_charging_points', 'ARS': 'AGS'}, inplace=True)
        merged_gdf = gdf_districts.merge(charging_points_per_district, on='AGS', how='left')
        merged_gdf['num_charging_points'] = merged_gdf['num_charging_points'].fillna(0)
        
        gdf_for_map = merged_gdf[['AGS', 'GEN', 'geometry', 'num_charging_points']].copy()

        m = folium.Map(location=[51.16, 10.45], tiles="CartoDB positron", zoom_start=6, min_zoom=6)
        
        non_zero_data = gdf_for_map[gdf_for_map['num_charging_points'] > 0]['num_charging_points']
        if not non_zero_data.empty and non_zero_data.nunique() > 1:
            bins = list(non_zero_data.quantile([0, 0.2, 0.4, 0.6, 0.8, 1.0]).unique())
            while len(bins) < 3 and len(bins) > 0:
                bins.append(bins[-1] * 1.1)
        else:
            max_val = gdf_for_map['num_charging_points'].max()
            bins = [0, max_val / 2, max_val] if max_val > 0 else [0, 1]

        folium.Choropleth(
            geo_data=gdf_for_map,
            data=gdf_for_map,
            columns=['AGS', 'num_charging_points'],
            key_on='feature.properties.AGS',
            fill_color='Greens',
            fill_opacity=0.7,
            line_opacity=0.2,
            legend_name='Anzahl der Ladepunkte',
            highlight=True,
            bins=bins
        ).add_to(m)

        folium.GeoJson(
            gdf_for_map,
            style_function=lambda x: {'fillColor': 'transparent', 'color': 'transparent'},
            tooltip=folium.GeoJsonTooltip(
                fields=['GEN', 'num_charging_points'],
                aliases=['Landkreis:', 'Ladepunkte:'],
                sticky=True
            )
        ).add_to(m)
        
        st_folium(m, use_container_width=True, height=600)
    elif df_filtered.empty:
        st.warning("Für die aktuelle Filterauswahl gibt es keine Daten. Bitte ändere die Filter.")
    else:
        st.warning("Geodaten konnten nicht geladen werden. Die Karte wird nicht angezeigt.")