"""Zentrale Konfiguration: Seiteneinstellung, Farben und Konstanten.

Alle "Magic Numbers" und Beschriftungen, die an mehreren Stellen im Dashboard
gebraucht werden, leben hier, damit die Render-Funktionen lesbar bleiben.
"""

import streamlit as st

# --- SEITENKONFIGURATION ---
PAGE_TITLE = "Ladeinfrastruktur in Deutschland | NOW GmbH"


def configure_page():
    """Setzt die Streamlit-Seitenkonfiguration. Muss als erster st-Aufruf laufen."""
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")


# --- FARBPALETTE (NOW GmbH) ---
NOW_GRUEN = "#00B092"
NOW_DUNKELBLAU = "#003247"
NOW_GRAU = "#D3D3D3"

# --- LEISTUNGSKATEGORIEN ---
# Schwellen in kW, nach denen ein Ladepunkt eingeordnet wird.
HPC_THRESHOLD_KW = 150  # >= 150 kW  -> HPC
SCHNELL_THRESHOLD_KW = 22  # >  22 kW   -> Schnellladen, sonst Normalladen

KAT_HPC = "HPC-Laden (>= 150 kW)"
KAT_SCHNELL = "Schnellladen (> 22 kW)"
KAT_NORMAL = "Normalladen (<= 22 kW)"

LEISTUNGS_COLORS = {
    KAT_HPC: NOW_GRUEN,
    KAT_SCHNELL: NOW_DUNKELBLAU,
    KAT_NORMAL: NOW_GRAU,
}

# Feste Reihenfolge nach Leistung (absteigend), damit Filter und Charts nicht
# alphabetisch mischen. Deckt sich mit der Einfuegereihenfolge von LEISTUNGS_COLORS.
LEISTUNGS_KATEGORIEN = [KAT_HPC, KAT_SCHNELL, KAT_NORMAL]

# --- ZEITREIHEN ---
CHART_START_YEAR = (
    2010  # Charts beginnen ab diesem Jahr; Älteres wird als Offset kumuliert.
)

# --- KARTE ---
MAP_CENTER = [51.16, 10.45]
MAP_BOUNDS = [[47.27, 5.87], [55.06, 15.04]]
MAP_ZOOM = 6
SIMPLIFY_TOLERANCE = (
    500  # Vereinfachung der Kreisgeometrien (in Einheiten des Quell-CRS).
)
TARGET_CRS = 4326
