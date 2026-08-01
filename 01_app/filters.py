"""Seitenleisten-Filter: Rendern der Bedienelemente und Anwenden auf die Daten."""

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from config import LEISTUNGS_KATEGORIEN

# session_state-Keys der Filter-Widgets; der Reset-Button entfernt genau diese.
_FILTER_KEYS = (
    "flt_jahre",
    "flt_bundesland",
    "flt_leistung",
    "flt_kreis",
    "flt_betreiber",
)


@dataclass
class Filters:
    """Vom Nutzer in der Seitenleiste gewählte Filterwerte."""

    jahre: tuple[int, int]
    bundeslaender: list[str]
    leistungstypen: list[str]
    kreise: list[str]
    betreiber: list[str]


def _zeitraum_presets(
    min_jahr: int, max_jahr: int
) -> list[tuple[str, tuple[int, int]]]:
    """Liefert die Zeitraum-Schnellauswahl als ``(Label, (von, bis))``-Paare.

    :param min_jahr: kleinstes verfügbares Jahr.
    :param max_jahr: größtes verfügbares Jahr.
    :return: Presets, auf den verfügbaren Bereich geklemmt und ohne doppelte Spannen.
    """
    kandidaten = [
        ("Gesamt", (min_jahr, max_jahr)),
        ("Seit 2020", (max(min_jahr, 2020), max_jahr)),
        ("Letzte 5 J.", (max(min_jahr, max_jahr - 4), max_jahr)),
    ]
    presets: list[tuple[str, tuple[int, int]]] = []
    gesehen: set[tuple[int, int]] = set()
    for label, spanne in kandidaten:
        von, bis = spanne
        if von > bis or spanne in gesehen:
            continue
        gesehen.add(spanne)
        presets.append((label, spanne))
    return presets


def render_sidebar(df: pd.DataFrame) -> Filters:
    """Zeichnet die Filter-Seitenleiste und gibt die gewählten Werte zurück."""
    st.sidebar.header("Filteroptionen")

    # Setzt alle Filter auf ihre Startwerte zurueck, indem die Widget-Keys aus
    # dem session_state entfernt werden; der rerun zeichnet sie mit Defaults neu.
    if st.sidebar.button("Filter zurücksetzen", use_container_width=True):
        for key in _FILTER_KEYS:
            st.session_state.pop(key, None)
        st.rerun()

    # --- Zeitraum ---
    st.sidebar.markdown("**Zeitraum**")
    min_jahr, max_jahr = int(df["Jahr"].min()), int(df["Jahr"].max())
    # Slider ueber session_state vorbelegen (statt value=), damit die Presets ihn
    # setzen koennen, ohne die "default + session_state"-Warnung auszuloesen.
    if "flt_jahre" not in st.session_state:
        st.session_state["flt_jahre"] = (min_jahr, max_jahr)

    presets = _zeitraum_presets(min_jahr, max_jahr)
    for col, (label, spanne) in zip(st.sidebar.columns(len(presets)), presets):
        if col.button(label, use_container_width=True):
            st.session_state["flt_jahre"] = spanne
            st.rerun()

    selected_jahre = st.sidebar.slider(
        "Jahr:", min_value=min_jahr, max_value=max_jahr, key="flt_jahre"
    )

    # --- Region ---
    st.sidebar.markdown("**Region**")
    # Leere Auswahl bedeutet bewusst "alle": so startet das Widget aufgeräumt
    # (statt mit 16 Chips) und ein einzelnes Land ist ein Klick statt 15 Abwahlen.
    bundeslaender = sorted(df["Bundesland"].unique())
    selected_bundeslaender = st.sidebar.multiselect(
        "Bundesland:",
        options=bundeslaender,
        default=[],
        placeholder="Alle Bundesländer",
        help="Leer lassen = alle Bundesländer. Tippe zum Suchen, um einzelne auszuwählen.",
        key="flt_bundesland",
    )
    effektive_bundeslaender = selected_bundeslaender or bundeslaender

    # Kreis-Optionen auf die gewählten Bundesländer einschränken, damit keine
    # unmögliche Kombination (z. B. Bayern + ein NRW-Kreis) wählbar ist.
    kreise_optionen = sorted(
        df.loc[df["Bundesland"].isin(effektive_bundeslaender), "KreisKreisfreieStadt"]
        .dropna()
        .unique()
    )
    # Eine bereits getroffene Auswahl bereinigen, falls sie durch eine geänderte
    # Bundesland-Auswahl nicht mehr zu den Optionen passt (verhindert Streamlit-Fehler).
    if "flt_kreis" in st.session_state:
        st.session_state["flt_kreis"] = [
            k for k in st.session_state["flt_kreis"] if k in kreise_optionen
        ]
    # Kein default=, damit die manuelle session_state-Bereinigung keine Warnung wirft.
    selected_kreise = st.sidebar.multiselect(
        "Landkreis/Stadt:",
        options=kreise_optionen,
        placeholder="Alle Landkreise/Städte",
        help="Leer lassen = alle. Zeigt nur Kreise der gewählten Bundesländer.",
        key="flt_kreis",
    )

    # --- Ladepunkte ---
    st.sidebar.markdown("**Ladepunkte**")
    # Feste Reihenfolge (nach Leistung, absteigend) statt alphabetisch; pills sind
    # bei nur drei Kategorien scanbarer als ein Multiselect.
    vorhandene_leistungstypen = set(df["Leistungskategorie"].unique())
    leistungstypen = [k for k in LEISTUNGS_KATEGORIEN if k in vorhandene_leistungstypen]
    selected_leistungstypen = st.sidebar.pills(
        "Leistungstyp:",
        options=leistungstypen,
        selection_mode="multi",
        default=leistungstypen,
        key="flt_leistung",
    )

    betreiber = sorted(
        {b.strip() for b in df["BetreiberBereinigt"].dropna() if b.strip()}
    )
    selected_betreiber = st.sidebar.multiselect(
        "Betreiber:",
        options=betreiber,
        default=[],
        placeholder="Betreiber suchen…",
        help="Leer lassen = alle Betreiber. Tippe die ersten Buchstaben für Vorschläge.",
        key="flt_betreiber",
    )

    return Filters(
        jahre=selected_jahre,
        bundeslaender=effektive_bundeslaender,
        leistungstypen=selected_leistungstypen,
        kreise=selected_kreise,
        betreiber=selected_betreiber,
    )


def _format_de(n: int) -> str:
    """Formatiert eine ganze Zahl mit Punkt als Tausendertrennzeichen (de-DE)."""
    return f"{n:,}".replace(",", ".")


def render_result_count(df: pd.DataFrame, df_filtered: pd.DataFrame) -> None:
    """Zeigt in der Seitenleiste, wie viele Ladepunkte die Filter aktuell treffen."""
    st.sidebar.divider()
    st.sidebar.caption(
        f"**{_format_de(len(df_filtered))}** von {_format_de(len(df))} Ladepunkten"
    )


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Wendet alle Filter (inkl. Bundesland) auf den DataFrame an."""
    df_filtered = df[
        (df["Bundesland"].isin(f.bundeslaender))
        & (df["Jahr"] >= f.jahre[0])
        & (df["Jahr"] <= f.jahre[1])
        & (df["Leistungskategorie"].isin(f.leistungstypen))
    ]
    return _apply_selection(df_filtered, f)


def apply_filters_for_map(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Wie ``apply_filters``, aber ohne Bundesland-Filter (Karte ist gesamtdeutsch)."""
    df_filtered = df[
        (df["Jahr"] >= f.jahre[0])
        & (df["Jahr"] <= f.jahre[1])
        & (df["Leistungskategorie"].isin(f.leistungstypen))
    ]
    return _apply_selection(df_filtered, f)


def _apply_selection(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Wendet die Auswahl aus Kreis- und Betreiber-Combobox an."""
    if f.kreise:
        df = df[df["KreisKreisfreieStadt"].isin(f.kreise)]
    if f.betreiber:
        df = df[df["BetreiberBereinigt"].str.strip().isin(f.betreiber)]
    return df
