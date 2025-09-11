import streamlit as st
import pandas as pd
import plotly.express as px

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
        df = pd.read_csv('02_data/03_computed_data/combined_ladestation_ladepunkt.csv', low_memory=False)
        df['Inbetriebnahmedatum'] = pd.to_datetime(df['Inbetriebnahmedatum'], errors='coerce')
        df['Jahr'] = df['Inbetriebnahmedatum'].dt.year
        df.dropna(subset=['Inbetriebnahmedatum', 'Bundesland', 'KreisKreisfreieStadt'], inplace=True)
        
        def get_leistungskategorie(leistung):
            if leistung >= 150: return 'HPC-Laden (>= 150 kW)'
            elif leistung > 22: return 'Schnellladen (> 22 kW)'
            else: return 'Normalladen (<= 22 kW)'
        df['Leistungskategorie'] = df['LadeleistungInKW'].apply(get_leistungskategorie)
        
        return df
    except FileNotFoundError:
        st.error("FEHLER: Die Datei 'combined_ladestation_ladepunkt.csv' wurde nicht im selben Ordner gefunden.")
        return None

df = load_data()

if df is not None:
    # --- SIDEBAR & FILTER ---
    st.sidebar.header("Filteroptionen")

    # Jahr-Filter (bleibt slider)
    min_jahr, max_jahr = int(df['Jahr'].min()), int(df['Jahr'].max())
    selected_jahre = st.sidebar.slider("Zeitraum (Jahr):", min_value=min_jahr, max_value=max_jahr, value=(min_jahr, max_jahr))
    
    # Bundesland-Filter (bleibt multiselect)
    bundeslaender = sorted(df['Bundesland'].unique())
    selected_bundeslaender = st.sidebar.multiselect("Bundesland:", options=bundeslaender, default=bundeslaender)

    # --- NEU: Text-Suchfeld für Landkreis/Stadt ---
    search_kreis = st.sidebar.text_input("Landkreis/Stadt (Suche):")

      # --- NEU: Text-Suchfeld für Betreiber ---
    search_betreiber = st.sidebar.text_input("Betreiber (Suche):")

    
    # Leistungstyp-Filter (bleibt multiselect)
    leistungstypen = sorted(df['Leistungskategorie'].unique())
    selected_leistungstypen = st.sidebar.multiselect("Leistungstyp:", options=leistungstypen, default=leistungstypen)


    # Anwendungsfall-Filter (bleibt multiselect)
    use_cases = sorted(df['LadeUseCase'].dropna().unique())
    selected_use_cases = st.sidebar.multiselect("Anwendungsfall:", options=use_cases, default=use_cases)

   



    # --- DATENFILTERUNG (angepasst für Textsuche) ---
    df_filtered = df[
        (df['Bundesland'].isin(selected_bundeslaender)) &
        (df['Jahr'] >= selected_jahre[0]) &
        (df['Jahr'] <= selected_jahre[1]) &
        (df['Leistungskategorie'].isin(selected_leistungstypen)) &
        (df['LadeUseCase'].isin(selected_use_cases))
    ]

    # Wende Textfilter nur an, wenn etwas eingegeben wurde
    if search_kreis:
        df_filtered = df_filtered[df_filtered['KreisKreisfreieStadt'].str.contains(search_kreis, case=False, na=False)]
    
    if search_betreiber:
        df_filtered = df_filtered[df_filtered['BetreiberBereinigt'].str.contains(search_betreiber, case=False, na=False)]

    df_filtered = df_filtered.copy()


    # --- HAUPTSEITE (Rest des Codes bleibt gleich) ---
    st.title("⚡ Dashboard Ladeinfrastruktur Deutschland")
    st.markdown("Eine interaktive Analyse für die **NOW GmbH**.")

    # KPIs
    st.header("Statistische Kennzahlen (KPIs)")
    num_ladestationen = df_filtered['ladestation_id'].nunique()
    num_ladepunkte = len(df_filtered)
    leistung_ladepunkt_gw = df_filtered['LadeleistungInKW'].sum() / 1_000_000
    df_stationen_filtered = df_filtered.drop_duplicates(subset='ladestation_id')
    leistung_station_gw = df_stationen_filtered['InstallierteLadeleistungNLL'].sum() / 1_000_000
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Anzahl Ladestationen", f"{num_ladestationen:,}".replace(',', '.'))
    col2.metric("Anzahl Ladepunkte", f"{num_ladepunkte:,}".replace(',', '.'))
    col3.metric("Leistung nach Ladepunkt", f"{leistung_ladepunkt_gw:.2f} GW")
    col4.metric("Leistung nach Ladesäule", f"{leistung_station_gw:.2f} GW")
    st.divider()

    # Zeitreihen
    st.header("Entwicklung über die Zeit")
    col_ts1, col_ts2 = st.columns(2)
    with col_ts1:
        zubau_punkte = df_filtered.groupby(df_filtered['Inbetriebnahmedatum'].dt.year).size().reset_index(name='Anzahl')
        zubau_punkte.rename(columns={'Inbetriebnahmedatum': 'Jahr'}, inplace=True)
        fig_zubau_punkte = px.bar(zubau_punkte, x='Jahr', y='Anzahl', title='<b>Jährlicher Zubau von Ladepunkten</b>')
        fig_zubau_punkte.update_traces(marker_color=NOW_GRUEN)
        st.plotly_chart(fig_zubau_punkte, use_container_width=True)
    with col_ts2:
        zubau_stationen = df_stationen_filtered.groupby(df_stationen_filtered['Inbetriebnahmedatum'].dt.year).size().reset_index(name='Anzahl')
        zubau_stationen.rename(columns={'Inbetriebnahmedatum': 'Jahr'}, inplace=True)
        fig_zubau_stationen = px.bar(zubau_stationen, x='Jahr', y='Anzahl', title='<b>Jährlicher Zubau von Ladestationen</b>')
        fig_zubau_stationen.update_traces(marker_color=NOW_DUNKELBLAU)
        st.plotly_chart(fig_zubau_stationen, use_container_width=True)
    col_cum1, col_cum2 = st.columns(2)
    with col_cum1:
        df_sorted_punkte = df_filtered.sort_values('Inbetriebnahmedatum')
        cumulative_ladepunkte = df_sorted_punkte.groupby(pd.Grouper(key='Inbetriebnahmedatum', freq='M')).size().cumsum().reset_index(name='Anzahl')
        fig_cum_punkte = px.line(cumulative_ladepunkte, x='Inbetriebnahmedatum', y='Anzahl', title='<b>Kumulative Entwicklung der Ladepunkte</b>')
        fig_cum_punkte.update_traces(line_color=NOW_GRUEN)
        st.plotly_chart(fig_cum_punkte, use_container_width=True)
    with col_cum2:
        df_sorted_stationen = df_stationen_filtered.sort_values('Inbetriebnahmedatum')
        cumulative_stationen = df_sorted_stationen.groupby(pd.Grouper(key='Inbetriebnahmedatum', freq='M')).size().cumsum().reset_index(name='Anzahl')
        fig_cum_stationen = px.line(cumulative_stationen, x='Inbetriebnahmedatum', y='Anzahl', title='<b>Kumulative Entwicklung der Ladestationen</b>')
        fig_cum_stationen.update_traces(line_color=NOW_DUNKELBLAU)
        st.plotly_chart(fig_cum_stationen, use_container_width=True)
    st.divider()

    # Detaillierte Analysen
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