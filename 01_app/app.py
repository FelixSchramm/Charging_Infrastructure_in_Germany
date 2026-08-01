"""Streamlit-Dashboard: Ladeinfrastruktur in Deutschland.

Schlanker Entry-Point. Die eigentliche Logik liegt in:
- ``config.py``        – Seiteneinstellung, Farben, Konstanten
- ``data_loading.py``  – Laden/Vorbereiten der Daten (mit Caching)
- ``filters.py``       – Seitenleisten-Filter und ihre Anwendung
- ``sections/``        – je ein Modul pro Dashboard-Abschnitt

Start:  uv run streamlit run 01_app/app.py
"""

from config import configure_page

# Muss vor jedem anderen Streamlit-Aufruf stehen.
configure_page()

import streamlit as st

from data_loading import load_all
from filters import apply_filters, render_result_count, render_sidebar
from sections import (
    render_analyses,
    render_data_table,
    render_header,
    render_info,
    render_kpis,
    render_map,
)

# Mehr Abstand zwischen den Tab-Beschriftungen, solange die Breite reicht.
_TAB_STYLE = """
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 2.5rem; }
    </style>
"""

df, gdf_districts, df_kba = load_all()

if df is not None:
    filters = render_sidebar(df)

    # Titel und Datenstand bleiben ueber den Tabs immer sichtbar.
    render_header(df, df_kba)

    if not filters.leistungstypen:
        st.warning(
            "Bitte wähle mindestens einen Leistungstyp in der Seitenleiste aus, "
            "um die Auswertungen anzuzeigen."
        )
    else:
        df_filtered = apply_filters(df, filters)
        render_result_count(df, df_filtered)

        if df_filtered.empty:
            st.warning(
                "Für die aktuelle Filterauswahl gibt es keine Ladepunkte. "
                "Bitte passe die Filter an – zum Beispiel Bundesland, Landkreis/Stadt "
                "oder Betreiber, die nicht zusammenpassen."
            )
        else:
            st.markdown(_TAB_STYLE, unsafe_allow_html=True)
            tab_ueberblick, tab_betreiber, tab_regional, tab_daten, tab_info = st.tabs(
                [
                    "Überblick",
                    "Analysen",
                    "Landkreise",
                    "Daten",
                    "Hinweise",
                ]
            )

            with tab_ueberblick:
                render_kpis(df_filtered)
            with tab_betreiber:
                render_analyses(df_filtered)
            with tab_regional:
                render_map(df, gdf_districts, df_kba, filters)
            with tab_daten:
                render_data_table(df_filtered)
            with tab_info:
                render_info(df, df_kba)
