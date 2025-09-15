import streamlit as st
import pandas as pd
import plotly.express as px

# --- SEITENKONFIGURATION & FARBPALETTE ---
st.set_page_config(
    page_title="Ladeinfrastruktur in Deutschland | NOW GmbH",
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
        # Passe den Dateipfad entsprechend deiner Ordnerstruktur an
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
        st.error("FEHLER: Die Datei 'combined_ladestation_ladepunkt.csv' wurde nicht gefunden. Bitte überprüfe den Pfad.")
        return None

df = load_data()

if df is not None:
    # --- SEITENLEISTE MIT FILTERN ---
    st.sidebar.header("Filteroptionen")

    min_jahr, max_jahr = int(df['Jahr'].min()), int(df['Jahr'].max())
    selected_jahre = st.sidebar.slider("Zeitraum (Jahr):", min_value=min_jahr, max_value=max_jahr, value=(min_jahr, max_jahr))
    
    bundeslaender = sorted(df['Bundesland'].unique())
    selected_bundeslaender = st.sidebar.multiselect("Bundesland:", options=bundeslaender, default=bundeslaender)

    leistungstypen = sorted(df['Leistungskategorie'].unique())
    selected_leistungstypen = st.sidebar.multiselect("Leistungstyp:", options=leistungstypen, default=leistungstypen)

    use_cases = sorted(df['LadeUseCase'].dropna().unique())
    selected_use_cases = st.sidebar.multiselect("Anwendungsfall:", options=use_cases, default=use_cases)
    
    search_kreis = st.sidebar.text_input("Landkreis/Stadt (Suche):", "").lower()
    search_betreiber = st.sidebar.text_input("Betreiber (Suche):", "").lower()

    # --- DATENFILTERUNG ---
    df_filtered = df.copy()
    
    df_filtered = df_filtered[
        (df_filtered['Bundesland'].isin(selected_bundeslaender)) &
        (df_filtered['Jahr'] >= selected_jahre[0]) &
        (df_filtered['Jahr'] <= selected_jahre[1]) &
        (df_filtered['Leistungskategorie'].isin(selected_leistungstypen)) &
        (df_filtered['LadeUseCase'].isin(selected_use_cases))
    ]
    
    if search_kreis:
        df_filtered = df_filtered[df_filtered['KreisKreisfreieStadt'].str.lower().str.contains(search_kreis, na=False)]
    
    if search_betreiber:
        df_filtered = df_filtered[df_filtered['BetreiberBereinigt'].str.lower().str.contains(search_betreiber, na=False)]

    # --- HAUPTSEITE ---
    st.title("Stand der Ladeinfrastruktur in Deutschland")
    st.markdown("Eine interaktive Analyse für die **NOW GmbH**.")
    
    df_stationen_filtered = df_filtered.drop_duplicates(subset='ladestation_id')

    # KPIs
    st.header("Statistische Kennzahlen (KPIs)")
    col1, col2, col3, col4 = st.columns(4)
    num_ladestationen = df_stationen_filtered['ladestation_id'].nunique()
    num_ladepunkte = len(df_filtered)
    num_hpc_ladepunkte = len(df_filtered[df_filtered['LadeleistungInKW'] >= 150])
    leistung_stationen_sum = df_stationen_filtered['InstallierteLadeleistungNLL'].sum() / 1_000_000
    
    col1.metric("Anzahl Ladestationen", f"{num_ladestationen:,}".replace(',', '.'))
    col2.metric("Anzahl Ladepunkte", f"{num_ladepunkte:,}".replace(',', '.'))
    col3.metric("Anzahl HPC-Ladepunkte", f"{num_hpc_ladepunkte:,}".replace(',', '.'))
    col4.metric("Gesamtleistung", f"{leistung_stationen_sum:.2f} GW")
    
    st.divider()

    # --- Zeitreihen ---
    st.header("Entwicklung über die Zeit")

    # ERSTE REIHE: LADEPUNKTE (GESAMT)
    col_punkt_ges_1, col_punkt_ges_2 = st.columns(2)
    with col_punkt_ges_1:
        # Kumulative Entwicklung aller Ladepunkte nach Jahr
        cumulative_punkte = df_filtered.groupby('Jahr').size().cumsum().reset_index(name='Anzahl')
        fig_cum_punkte = px.line(cumulative_punkte, x='Jahr', y='Anzahl', title='<b>Kumulative Entwicklung der Ladepunkte (Gesamt)</b>')
        fig_cum_punkte.update_traces(line_color=NOW_DUNKELBLAU)
        st.plotly_chart(fig_cum_punkte, use_container_width=True, key="fig_cum_punkte")

    with col_punkt_ges_2:
        # Jährlicher Zubau aller Ladepunkte
        zubau_punkte_gesamt = df_filtered.groupby('Jahr').size().reset_index(name='Anzahl')
        fig_zubau_punkte_gesamt = px.line(zubau_punkte_gesamt, x='Jahr', y='Anzahl', title='<b>Jährlicher Zubau von Ladepunkten (Gesamt)</b>')
        fig_zubau_punkte_gesamt.update_traces(line_color=NOW_DUNKELBLAU)
        st.plotly_chart(fig_zubau_punkte_gesamt, use_container_width=True, key="fig_zubau_punkte_gesamt")

    # ZWEITE REIHE: LADEPUNKTE (NACH LEISTUNGSKATEGORIE)
    col_punkt_kat_1, col_punkt_kat_2 = st.columns(2)
    with col_punkt_kat_1:
        # Jährlicher Zubau von Ladepunkten nach Leistung
        zubau_punkte_kat = df_filtered.groupby(['Jahr', 'Leistungskategorie']).size().reset_index(name='Anzahl')
        
        # Sicherstellen, dass alle Jahre für jede Kategorie vorhanden sind
        jahre_kat = zubau_punkte_kat['Jahr'].unique()
        kategorien_kat = zubau_punkte_kat['Leistungskategorie'].unique()
        df_full_kat = pd.DataFrame({'Jahr': jahre_kat}).merge(pd.DataFrame({'Leistungskategorie': kategorien_kat}), how='cross')
        
        zubau_punkte_kat = df_full_kat.merge(zubau_punkte_kat, on=['Jahr', 'Leistungskategorie'], how='left').fillna(0)

        fig_zubau_punkte_kat = px.line(
            zubau_punkte_kat, 
            x='Jahr', 
            y='Anzahl', 
            color='Leistungskategorie',  
            title='<b>Jährlicher Zubau von Ladepunkten nach Leistung</b>'
        )
        
        color_map_line = {'HPC-Laden (>= 150 kW)': NOW_GRUEN, 'Schnellladen (> 22 kW)': NOW_DUNKELBLAU, 'Normalladen (<= 22 kW)': NOW_GRAU}
        for data in fig_zubau_punkte_kat.data:
            data.line.color = color_map_line.get(data.name, data.line.color)
        
        fig_zubau_punkte_kat.update_layout(
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
        )
        st.plotly_chart(fig_zubau_punkte_kat, use_container_width=True, key="fig_zubau_punkte_kat")

    with col_punkt_kat_2:
        # Kumulative Entwicklung der Ladepunkte nach Leistung und Jahr
        cumulative_ladepunkte_kat = df_filtered.groupby(['Jahr', 'Leistungskategorie']).size().reset_index(name='Anzahl')
        
        if not cumulative_ladepunkte_kat.empty:
            jahre_range = pd.RangeIndex(start=cumulative_ladepunkte_kat['Jahr'].min(), stop=cumulative_ladepunkte_kat['Jahr'].max() + 1)
            kategorien = cumulative_ladepunkte_kat['Leistungskategorie'].unique()
            
            full_index = pd.MultiIndex.from_product([jahre_range, kategorien], names=['Jahr', 'Leistungskategorie'])
            
            cumulative_ladepunkte_kat = cumulative_ladepunkte_kat.set_index(['Jahr', 'Leistungskategorie']).reindex(full_index, fill_value=0).reset_index()
            cumulative_ladepunkte_kat['Anzahl'] = cumulative_ladepunkte_kat.groupby('Leistungskategorie')['Anzahl'].cumsum()
        
        fig_cum_ladepunkte_kat = px.line(
            cumulative_ladepunkte_kat, 
            x='Jahr', 
            y='Anzahl', 
            color='Leistungskategorie',  
            title='<b>Kumulative Entwicklung der Ladepunkte nach Leistung</b>'
        )
        
        color_discrete_map = {'HPC-Laden (>= 150 kW)': NOW_GRUEN, 'Schnellladen (> 22 kW)': NOW_DUNKELBLAU, 'Normalladen (<= 22 kW)': NOW_GRAU}
        for data in fig_cum_ladepunkte_kat.data:
            data.line.color = color_discrete_map.get(data.name, data.line.color)
        
        fig_cum_ladepunkte_kat.update_layout(
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
        )
        st.plotly_chart(fig_cum_ladepunkte_kat, use_container_width=True, key="fig_cum_ladepunkte_kat")
        
    st.divider()

    # Detaillierte Analysen
    st.header("Detaillierte Analysen")
    col_detail1, col_detail2 = st.columns(2)
    with col_detail1:
        kategorie_counts = df_filtered['Leistungskategorie'].value_counts().reset_index()
        color_map_pie = {'HPC-Laden (>= 150 kW)': NOW_GRUEN, 'Schnellladen (> 22 kW)': NOW_DUNKELBLAU, 'Normalladen (<= 22 kW)': NOW_GRAU}
        fig_kategorien = px.pie(kategorie_counts, names='Leistungskategorie', values='count', title='<b>Anteil der Ladepunkttypen</b>', color='Leistungskategorie', color_discrete_map=color_map_pie)
        st.plotly_chart(fig_kategorien, use_container_width=True, key="fig_kategorien")
    with col_detail2:
        top_10_betreiber = df_filtered['BetreiberBereinigt'].value_counts().nlargest(10).reset_index()
        fig_betreiber = px.bar(top_10_betreiber, x='count', y='BetreiberBereinigt', orientation='h', title='<b>Top 10 Betreiber</b>', labels={'count': 'Anzahl Ladepunkte', 'BetreiberBereinigt': 'Betreiber'}, color_discrete_sequence=[NOW_GRUEN])
        fig_betreiber.update_layout(yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig_betreiber, use_container_width=True, key="fig_betreiber")

    # --- ABSCHNITT LIMITATIONEN ---
    st.divider()
    st.header("Limitationen")

    st.markdown("""
    Dieses Dashboard bietet einen umfassenden Überblick über den **Bestand** der öffentlichen Ladeinfrastruktur in Deutschland. Für eine vollständige Bewertung des Marktes müssen jedoch qualitative und ökonomische Faktoren berücksichtigt werden, die über eine reine Bestandszählung und historische Entwicklung hinausgehen.

    - **Auslastungsgrad:** Das Dashboard erfasst den Bestand, aber nicht die tatsächliche Nutzung der Ladeinfrastruktur. Geringe Auslastung ist für einige Standorte eine zentrale Herausforderung, die hier nicht abgebildet wird. Das kann mit Metriken wie **durchschnittliche Ladevorgänge pro Ladepunkt und Tag** oder **durchschnittlich verladene Energiemenge pro Ladepunkt und Tag** ergänzt werden.

    - **Verhältnis von Ladepunkten zu E-Fahrzeugen:** Die reine Anzahl an Ladepunkten pro Region ist nur bedingt aussagekräftig. Eine entscheidende Kennzahl ist das Verhältnis zum lokalen E-Fahrzeugbestand, um die tatsächliche Versorgungsdichte zu bewerten. Deutschlandweit teilen sich etwa zehn E-Autos einen öffentlichen Ladepunkt.

    - **Fehlende geografische Analyse:** Das Dashboard enthält keine interaktive Karte, wodurch "weiße Flecken" und regionale Ungleichgewichte nicht visuell analysiert werden können. Dies ließe sich durch Geodaten vom nationalen Open-Data-Portal [GovData.de](https://www.govdata.de/) beheben.
                            
    - **Zuverlässigkeit und Nutzererfahrung:** Gezählt werden alle registrierten Ladepunkte, unabhängig von ihrem Betriebszustand. Die tatsächliche Ausfallrate aus Nutzersicht ist ein entscheidender Qualitätsfaktor, der hier unberücksichtigt bleibt. Diese Diskrepanz zur offiziellen "Uptime" entsteht z.B. durch Softwarefehler oder defekte QR-Codes.

    - **Ökonomischer Kontext:** Faktoren wie der komplexe Tarifstrukturen, die durch über gewerbliche 8.000 Betreiber entstehen, Preismodelle und die allgemeine Wirtschaftlichkeit der Standorte werden nicht analysiert. Diese beeinflussen jedoch die Marktdynamik und den weiteren Ausbau maßgeblich.
    """)