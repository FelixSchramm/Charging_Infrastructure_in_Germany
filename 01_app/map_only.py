# dashboard.py

import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import io
from pathlib import Path 

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="German Charging Infrastructure",
    page_icon="🔌",
    layout="wide"
)

# --- 2. DATA LOADING AND PREPARATION ---
# Use a cached function for better performance. Streamlit will only run this
# function once, unless the code or input data changes.
@st.cache_data
def load_data():
    # --- Create a portable file path ---
    # Gets the path to the directory of the current script (e.g., 01_app)
    script_dir = Path(__file__).parent
    # Goes up one level to the project's root folder
    project_root = script_dir.parent
    # Builds the full path to the shapefile from the project root
    shapefile_path = project_root / "02_data/02_meta_data/vg250_01-01.gk3.shape.ebenen/vg250_ebenen_0101/VG250_KRS.shp"
    
    # --- Load and process data ---
    # Load the geospatial data of German districts
    gdf_districts = gpd.read_file(shapefile_path)

    # Convert any datetime columns to strings to prevent JSON errors
    for col in gdf_districts.columns:
        if pd.api.types.is_datetime64_any_dtype(gdf_districts[col]):
            gdf_districts[col] = gdf_districts[col].astype(str)

    # Load your charging station data
    # For this example, we create it here. In your project, you would load your CSV.
    csv_data_string = """AGS,num_charging_points
01001,150
01002,280
08111,950
09162,1200
05315,750
16056,95
"""
    df_charging_data = pd.read_csv(io.StringIO(csv_data_string), dtype={'AGS': str})

    # Merge the datasets to combine charging data with district shapes
    merged_gdf = gdf_districts.merge(df_charging_data, on='AGS', how='left')
    # Fill any districts with no data with 0 for visualization
    merged_gdf['num_charging_points'] = merged_gdf['num_charging_points'].fillna(0)
    
    return merged_gdf

# --- 3. STREAMLIT APP LAYOUT ---
st.title("🔌 Charging Infrastructure in Germany")
st.markdown("This dashboard visualizes the number of electric vehicle charging points across German districts.")

# Load the prepared data
gdf = load_data()

# --- 4. CREATE THE FOLIUM MAP ---
# Define the geographic bounding box for Germany to frame the map
germany_bounds = [[47.2, 5.8], [55.1, 15.1]]

# Create the map object with options to restrict view
m = folium.Map(
    location=[51.16, 10.45], 
    tiles="CartoDB positron",
    max_bounds=True,
    min_zoom=6,
    zoom_start=6,
    max_lat=56, min_lat=47, max_lon=16, min_lon=5
)
m.fit_bounds(germany_bounds)

# Calculate quantile bins for a more effective and visually appealing color scale
non_zero_data = gdf[gdf['num_charging_points'] > 0]['num_charging_points']
if not non_zero_data.empty:
    bins = list(non_zero_data.quantile([0, 0.25, 0.5, 0.75, 1.0]).drop_duplicates())
    if bins[0] > 0:
        bins.insert(0, 0)
else:
    bins = [0, 1]

# Create the choropleth layer using our calculated bins
folium.Choropleth(
    geo_data=gdf,
    name='Choropleth',
    data=gdf,
    columns=['AGS', 'num_charging_points'],
    key_on='feature.properties.AGS',
    fill_color='YlOrRd',
    fill_opacity=0.7,
    line_opacity=0.2,
    legend_name='Number of Charging Points',
    highlight=True,
    bins=bins
).add_to(m)

# Add a tooltip layer to show information on hover
folium.GeoJson(
    gdf,
    style_function=lambda x: {'fillColor': 'transparent', 'color': 'transparent'},
    tooltip=folium.GeoJsonTooltip(
        fields=['GEN', 'num_charging_points'],
        aliases=['District:', 'Charging Points:'],
        sticky=True
    )
).add_to(m)

# --- 5. DISPLAY THE MAP IN STREAMLIT ---
st.subheader("Interactive Map of Charging Points")
st_folium(m, width=1200, height=800)
st.info("Hover over a district to see its name and the number of charging points.")