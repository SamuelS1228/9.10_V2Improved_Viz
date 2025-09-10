
import os
import streamlit as st
import pandas as pd
import pydeck as pdk

# ──────────────────────────────────────────────────────────
# Map provider / token handling (Mapbox if available, else Carto)
# ──────────────────────────────────────────────────────────
_MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY")
if not _MAPBOX_TOKEN:
    try:
        _MAPBOX_TOKEN = st.secrets["MAPBOX_API_KEY"]  # type: ignore[attr-defined]
    except Exception:
        _MAPBOX_TOKEN = None

if _MAPBOX_TOKEN:
    pdk.settings.mapbox_api_key = _MAPBOX_TOKEN

# Colour palette (safe defaults)
_COL = [
    [31, 119, 180],
    [255, 127, 14],
    [44, 160, 44],
    [214, 39, 40],
    [148, 103, 189],
    [140, 86, 75],
    [227, 119, 194],
    [127, 127, 127],
    [188, 189, 34],
    [23, 190, 207],
] * 10  # repeat

def _c(i: int):
    i = int(i) if i is not None else 0
    return _COL[i % len(_COL)]

def _build_deck(layers):
    view_state = pdk.ViewState(latitude=39.5, longitude=-98.35, zoom=3.2, pitch=0)
    if _MAPBOX_TOKEN:
        return pdk.Deck(
            layers=layers,
            initial_view_state=view_state,
            map_style="mapbox://styles/mapbox/light-v11",
        )
    else:
        # Free Carto basemap (no token required)
        return pdk.Deck(
            layers=layers,
            initial_view_state=view_state,
            map_provider="carto",
            map_style="light"
        )

def plot_network(stores: pd.DataFrame, centers):
    """Render the outbound network on an interactive map."""
    st.subheader("Network Map")
    cen_df = pd.DataFrame(centers, columns=["Lon", "Lat"])

    edges = [
        {
            "f": [r.Longitude, r.Latitude],
            "t": [cen_df.iloc[int(r.Warehouse)].Lon, cen_df.iloc[int(r.Warehouse)].Lat],
            "col": _c(int(r.Warehouse)) + [120],
        }
        for r in stores.itertuples()
    ]
    line_layer = pdk.Layer(
        "LineLayer",
        edges,
        get_source_position="f",
        get_target_position="t",
        get_color="col",
        get_width=2,
        pickable=True,
        auto_highlight=True,
    )
    cen_df[["r","g","b"]] = [_c(i) for i in range(len(cen_df))]
    pts_layer = pdk.Layer(
        "ScatterplotLayer",
        cen_df,
        get_position="[Lon,Lat]",
        get_fill_color="[r,g,b]",
        get_radius=35000,
        opacity=0.9,
    )
    deck = _build_deck([line_layer, pts_layer])
    st.pydeck_chart(deck)

def summary(stores: pd.DataFrame, total: float, out_: float, in_: float, trans: float, wh: float,
            centers, demand, sqft_per_lb: float, has_tier1: bool, show_inbound: bool, show_trans: bool):
    st.subheader("Cost Summary")
    cols = st.columns(4 if (show_inbound or show_trans) else 3)
    i = 0
    cols[i].metric("Total", f"${total:,.0f}"); i += 1
    cols[i].metric("Outbound", f"${out_:,.0f}"); i += 1
    if show_inbound:
        cols[i].metric("Inbound", f"${in_:,.0f}"); i += 1
    if show_trans:
        cols[i].metric("Transfers", f"${trans:,.0f}"); i += 1
    cols[i].metric("Warehousing", f"${wh:,.0f}")

    df = pd.DataFrame(centers, columns=["Lon", "Lat"])
    df["DemandLbs"] = demand
    df["SqFt"] = df["DemandLbs"] * sqft_per_lb
    st.subheader("Warehouse Demand & Size")
    st.dataframe(df[["DemandLbs", "SqFt", "Lat", "Lon"]].style.format({"DemandLbs": ":,", "SqFt": ":,"}))

def plot_flows(lanes_df: pd.DataFrame, centers, flow_types=("outbound","transfer","inbound"), brand_filter="__ALL__"):
    """Interactive flow map with type toggles and brand filter.
    Colors:
      • Outbound/Transfer lines are colored by destination warehouse index (wh_idx) via _c(wh_idx).
      • Inbound lines are colored by tier1_idx if present; else by wh_idx if present; else fallback per-type color.
    """
    st.subheader("Flow Map")
    if lanes_df is None or lanes_df.empty:
        st.info("No lanes to display.")
        return
    df = lanes_df.copy()

    # Brand filter
    if brand_filter != "__ALL__" and "brand" in df.columns:
        df = df[df["brand"].astype(str) == str(brand_filter)]

    # Flow type filter
    df = df[df["lane_type"].isin(list(flow_types))]
    if df.empty:
        st.info("No flows match the current filters.")
        return

    # Positions
    df["origin_lon_lat"] = df[["origin_lon","origin_lat"]].values.tolist()
    df["dest_lon_lat"] = df[["dest_lon","dest_lat"]].values.tolist()

    # Per-row RGBA
    colors = []
    for r in df.itertuples():
        col = None
        if r.lane_type in ("outbound","transfer") and hasattr(r, "wh_idx") and getattr(r, "wh_idx") is not None:
            col = _c(int(r.wh_idx)) + [160]
        elif r.lane_type == "inbound":
            if hasattr(r, "tier1_idx") and getattr(r, "tier1_idx") is not None:
                col = _c(int(r.tier1_idx)) + [140]
            elif hasattr(r, "wh_idx") and getattr(r, "wh_idx") is not None:
                col = _c(int(r.wh_idx)) + [140]
        if col is None:
            col = {"outbound":[0,128,255,160], "transfer":[255,127,14,180], "inbound":[44,160,44,140]}.get(r.lane_type,[127,127,127,140])
        colors.append(col)
    df["rgba"] = colors

    # Layers
    layers = []
    def _line_layer(df_sub, width):
        return pdk.Layer(
            "LineLayer",
            df_sub,
            get_source_position="origin_lon_lat",
            get_target_position="dest_lon_lat",
            get_color="rgba",
            get_width=width,
            pickable=True,
            auto_highlight=True,
        )

    out_df = df[df["lane_type"]=="outbound"]
    if not out_df.empty and "outbound" in flow_types:
        layers.append(_line_layer(out_df, 2))

    tr_df = df[df["lane_type"]=="transfer"]
    if not tr_df.empty and "transfer" in flow_types:
        layers.append(_line_layer(tr_df, 3))

    in_df = df[df["lane_type"]=="inbound"]
    if not in_df.empty and "inbound" in flow_types:
        layers.append(_line_layer(in_df, 1))

    # Centers
    cen_df = pd.DataFrame(centers, columns=["Lon","Lat"])
    cen_df[["r","g","b"]] = [_c(i) for i in range(len(cen_df))]
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        cen_df,
        get_position="[Lon,Lat]",
        get_fill_color="[r,g,b]",
        get_radius=35000,
        opacity=0.9,
    ))

    deck = _build_deck(layers)
    st.pydeck_chart(deck)
