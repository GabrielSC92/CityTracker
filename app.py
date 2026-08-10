"""City Tracker -- a personal map of everywhere you have been.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import html
from datetime import date

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Fullscreen, MarkerCluster
from streamlit_folium import st_folium

import db
import geocode
from continents import continent_for, flag

STATUS_STYLE = {
    "visited": {"color": "green", "icon": "check", "emoji": "✅"},
    "wishlist": {"color": "blue", "icon": "star", "emoji": "⭐"},
}
TILE_OPTIONS = {
    "Light": "CartoDB positron",
    "Dark": "CartoDB dark_matter",
    "Street": "OpenStreetMap",
}
# Leaflet renders the basemap's own attribution inside the map, which covers the
# Map tab only. Every tab shows geocoded place data, so the credit is repeated as
# a page footer.
ATTRIBUTION = (
    "Place data © [OpenStreetMap](https://www.openstreetmap.org/copyright) "
    "contributors, licensed under "
    "[ODbL](https://opendatacommons.org/licenses/odbl/1-0/) · "
    "geocoding by [Photon](https://photon.komoot.io) and "
    "[Nominatim](https://nominatim.openstreetmap.org)"
)

st.set_page_config(page_title="City Tracker", page_icon="🌍", layout="wide")
db.init_db()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(query: str, limit: int) -> geocode.SearchResponse:
    return geocode.search(query, limit)


def refresh() -> None:
    """Drop cached rows and rerun so the map reflects the change immediately."""
    load_places.clear()
    st.rerun()


@st.cache_data(show_spinner=False)
def load_places() -> pd.DataFrame:
    return db.load_places()


# --------------------------------------------------------------------------
# Sidebar: search, add, filter
# --------------------------------------------------------------------------

places = load_places()

with st.sidebar:
    st.title("🌍 City Tracker")

    st.subheader("Feature search")
    st.caption(
        "Search a landmark, park, mountain or town — the exact city is resolved for you."
    )

    with st.form("search_form", clear_on_submit=False):
        query = st.text_input(
            "What do you remember?",
            placeholder="Puy du Fou · Cachoeirinha · Machu Picchu",
            label_visibility="collapsed",
        )
        limit = st.slider("Max results", 5, 25, 10)
        searched = st.form_submit_button("Search", type="primary", width="stretch")

    if searched:
        if query.strip():
            with st.spinner("Searching OpenStreetMap…"):
                response = cached_search(query.strip(), limit)
            st.session_state["results"] = response.results
            st.session_state["warnings"] = response.warnings
        else:
            st.session_state["results"] = []
            st.session_state["warnings"] = ["Type something to search for."]

    for warning in st.session_state.get("warnings", []):
        st.info(warning, icon="ℹ️")

    results: list[geocode.Place] = st.session_state.get("results", [])
    if results:
        choice = st.radio(
            f"{len(results)} match(es)",
            options=range(len(results)),
            format_func=lambda i: f"{flag(results[i].country_code)} {results[i].label}",
        )
        picked = results[choice]

        st.caption(picked.display_name or picked.where)
        st.caption(
            f"📍 {picked.lat:.4f}, {picked.lon:.4f} · "
            f"{continent_for(picked.country_code)} · via {', '.join(picked.sources)}"
        )

        with st.form("add_form"):
            label = st.text_input("Save as", value=picked.name)
            status = st.selectbox(
                "Status", db.STATUSES, format_func=lambda s: f"{STATUS_STYLE[s]['emoji']} {s.title()}"
            )
            when = st.date_input("Visited on", value=None, format="YYYY-MM-DD")
            rating = st.slider("Rating", 0, 5, 0, help="0 = not rated")
            notes = st.text_area("Notes", placeholder="Who you went with, what you saw…")

            if st.form_submit_button("➕ Add to my map", type="primary", width="stretch"):
                place_id, created = db.add_place(
                    name=label.strip() or picked.name,
                    display_name=picked.display_name,
                    category=picked.category,
                    feature_type=picked.feature_type,
                    city=picked.city,
                    state=picked.state,
                    country=picked.country,
                    country_code=picked.country_code,
                    lat=picked.lat,
                    lon=picked.lon,
                    osm_type=picked.osm_type,
                    osm_id=picked.osm_id,
                    status=status,
                    visited_on=when.isoformat() if isinstance(when, date) else None,
                    rating=rating or None,
                    notes=notes.strip(),
                )
                if created:
                    st.toast(f"Added {label or picked.name}", icon="🎉")
                    refresh()
                else:
                    st.warning("Already on your map.")

    with st.expander("Add manually (no search)"):
        with st.form("manual_form", clear_on_submit=True):
            m_name = st.text_input("Name")
            m_country = st.text_input("Country")
            m_code = st.text_input("Country code (ISO-2)", max_chars=2)
            col_a, col_b = st.columns(2)
            m_lat = col_a.number_input("Latitude", -90.0, 90.0, 0.0, format="%.6f")
            m_lon = col_b.number_input("Longitude", -180.0, 180.0, 0.0, format="%.6f")
            m_status = st.selectbox("Status", db.STATUSES, key="manual_status")
            m_when = st.date_input("Visited on", value=None, key="manual_date", format="YYYY-MM-DD")

            if st.form_submit_button("Add", width="stretch"):
                if m_name.strip():
                    db.add_place(
                        name=m_name.strip(),
                        country=m_country.strip(),
                        country_code=m_code.strip(),
                        lat=m_lat,
                        lon=m_lon,
                        status=m_status,
                        visited_on=m_when.isoformat() if isinstance(m_when, date) else None,
                    )
                    st.toast(f"Added {m_name}", icon="🎉")
                    refresh()
                else:
                    st.warning("A name is required.")

    st.divider()
    st.subheader("Filters")
    status_filter = st.multiselect("Status", db.STATUSES, default=list(db.STATUSES))
    continent_filter = st.multiselect(
        "Continent", sorted(places["continent"].dropna().unique()) if not places.empty else []
    )
    country_filter = st.multiselect(
        "Country", sorted(places["country"].dropna().unique()) if not places.empty else []
    )

    st.divider()
    st.caption(f"Database: `{db.DB_PATH.name}` in `data/`")


# --------------------------------------------------------------------------
# Apply filters
# --------------------------------------------------------------------------

view = places.copy()
if not view.empty:
    if status_filter:
        view = view[view["status"].isin(status_filter)]
    if continent_filter:
        view = view[view["continent"].isin(continent_filter)]
    if country_filter:
        view = view[view["country"].isin(country_filter)]


# --------------------------------------------------------------------------
# Header metrics
# --------------------------------------------------------------------------

visited = view[view["status"] == "visited"] if not view.empty else view

cols = st.columns(4)
cols[0].metric("Places", len(view))
cols[1].metric("Countries", visited["country_code"].replace("", pd.NA).nunique() if not visited.empty else 0)
known_continents = visited[visited["continent"] != "Unknown"] if not visited.empty else visited
cols[2].metric("Continents", known_continents["continent"].nunique() if not visited.empty else 0)
cols[3].metric("Wishlist", int((view["status"] == "wishlist").sum()) if not view.empty else 0)

map_tab, list_tab, stats_tab = st.tabs(["🗺️ Map", "📋 Places", "📊 Stats"])


# --------------------------------------------------------------------------
# Map
# --------------------------------------------------------------------------

with map_tab:
    controls = st.columns([1, 1, 3])
    tile_name = controls[0].selectbox("Style", list(TILE_OPTIONS))
    cluster_on = controls[1].toggle("Cluster markers", value=True)

    world = folium.Map(
        location=[20, 0],
        zoom_start=2,
        tiles=TILE_OPTIONS[tile_name],
        world_copy_jump=True,
    )
    Fullscreen().add_to(world)
    layer = MarkerCluster().add_to(world) if cluster_on else world

    for row in view.itertuples():
        style = STATUS_STYLE.get(row.status, STATUS_STYLE["visited"])
        when = row.visited_on.strftime("%d %b %Y") if pd.notna(row.visited_on) else "—"
        stars = "★" * int(row.rating) if pd.notna(row.rating) and row.rating else ""
        where = ", ".join(part for part in (row.city, row.state, row.country) if part)

        popup = f"""
            <div style="font-family:system-ui;min-width:200px">
              <b>{html.escape(str(row.name))}</b><br>
              <span style="color:#666">{html.escape(where)}</span><br>
              <span style="color:#666">{html.escape(str(row.feature_type).replace("_", " ").title())}</span>
              <hr style="margin:6px 0">
              {style['emoji']} {row.status.title()} · {when} {stars}
              {'<br><i>' + html.escape(str(row.notes)) + '</i>' if row.notes else ''}
            </div>
        """
        folium.Marker(
            location=[row.lat, row.lon],
            tooltip=f"{flag(row.country_code)} {row.name}",
            popup=folium.Popup(popup, max_width=320),
            icon=folium.Icon(color=style["color"], icon=style["icon"], prefix="fa"),
        ).add_to(layer)

    if not view.empty:
        pad = 1.0
        world.fit_bounds(
            [
                [view["lat"].min() - pad, view["lon"].min() - pad],
                [view["lat"].max() + pad, view["lon"].max() + pad],
            ]
        )

    # returned_objects=[] stops panning/zooming from triggering a Streamlit rerun.
    # The key changes whenever the rendered rows change, so edits show up at once.
    fingerprint = pd.util.hash_pandas_object(view[["id", "status", "lat", "lon"]]).sum()
    st_folium(
        world,
        use_container_width=True,
        height=620,
        returned_objects=[],
        key=f"map-{tile_name}-{cluster_on}-{len(view)}-{fingerprint}",
    )

    if view.empty:
        st.info("Nothing on the map yet — search for a place in the sidebar to begin.", icon="👈")


# --------------------------------------------------------------------------
# Editable list
# --------------------------------------------------------------------------

with list_tab:
    if view.empty:
        st.info("No places match the current filters.")
    else:
        editable = view[
            ["id", "name", "city", "state", "country", "feature_type",
             "status", "visited_on", "rating", "notes"]
        ].copy()
        editable.insert(0, "delete", False)

        edited = st.data_editor(
            editable,
            hide_index=True,
            width="stretch",
            num_rows="fixed",
            height=520,
            key="places_editor",
            column_config={
                "delete": st.column_config.CheckboxColumn("🗑", width="small"),
                "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "name": st.column_config.TextColumn("Name"),
                "city": st.column_config.TextColumn("City", disabled=True),
                "state": st.column_config.TextColumn("Region", disabled=True),
                "country": st.column_config.TextColumn("Country", disabled=True),
                "feature_type": st.column_config.TextColumn("Type", disabled=True),
                "status": st.column_config.SelectboxColumn("Status", options=list(db.STATUSES)),
                "visited_on": st.column_config.DateColumn("Visited on", format="YYYY-MM-DD"),
                "rating": st.column_config.NumberColumn("Rating", min_value=0, max_value=5, step=1),
                "notes": st.column_config.TextColumn("Notes", width="large"),
            },
        )

        action = st.columns([1, 1, 4])
        if action[0].button("💾 Save changes", type="primary", width="stretch"):
            original = editable.set_index("id")
            changed = 0
            for row in edited.itertuples():
                before = original.loc[row.id]
                updates = {}
                for field in db.EDITABLE_FIELDS:
                    new = getattr(row, field)
                    old = before[field]
                    if field == "visited_on":
                        # The editor hands back Timestamps; the DB stores plain dates.
                        new = pd.Timestamp(new).strftime("%Y-%m-%d") if pd.notna(new) else None
                        old = pd.Timestamp(old).strftime("%Y-%m-%d") if pd.notna(old) else None
                    elif field == "rating":
                        new = int(new) if pd.notna(new) and new else None
                        old = int(old) if pd.notna(old) and old else None
                    else:
                        new = "" if new is None else str(new)
                        old = "" if pd.isna(old) else str(old)
                    if new != old:
                        updates[field] = new
                if updates:
                    db.update_place(int(row.id), **updates)
                    changed += 1
            st.toast(f"Saved {changed} change(s)", icon="💾")
            refresh()

        to_delete = [int(i) for i in edited.loc[edited["delete"], "id"]]
        if action[1].button(
            f"Delete ({len(to_delete)})", disabled=not to_delete, width="stretch"
        ):
            db.delete_places(to_delete)
            st.toast(f"Deleted {len(to_delete)} place(s)", icon="🗑️")
            refresh()

        st.download_button(
            "⬇️ Export CSV",
            data=places.to_csv(index=False).encode("utf-8"),
            file_name="city-tracker.csv",
            mime="text/csv",
        )
        st.caption(
            "The export carries OpenStreetMap-derived fields. If you publish it, "
            "credit © OpenStreetMap contributors (ODbL)."
        )


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

with stats_tab:
    if visited.empty:
        st.info("Add some visited places to see stats.")
    else:
        left, right = st.columns(2)

        by_continent = (
            visited.groupby("continent").size().sort_values(ascending=False).rename("places")
        )
        left.subheader("By continent")
        left.bar_chart(by_continent, horizontal=True)

        named = visited[visited["country"].astype(str).str.strip() != ""]
        by_country = (
            named.assign(label=named["country_code"].map(flag) + " " + named["country"])
            .groupby("label")
            .size()
            .sort_values(ascending=False)
            .head(15)
            .rename("places")
        )
        right.subheader("Top countries")
        right.bar_chart(by_country, horizontal=True)

        dated = visited[visited["visited_on"].notna()]
        if not dated.empty:
            st.subheader("Places per year")
            per_year = dated.groupby(dated["visited_on"].dt.year).size().rename("places")
            per_year.index = per_year.index.astype(int).astype(str)
            st.bar_chart(per_year)

        st.subheader("Countries")
        summary = (
            visited.groupby(["continent", "country_code", "country"])
            .agg(places=("id", "count"), first_visit=("visited_on", "min"))
            .reset_index()
            .sort_values(["continent", "places"], ascending=[True, False])
        )
        summary.insert(0, "Flag", summary["country_code"].map(flag))
        st.dataframe(
            summary.drop(columns=["country_code"]),
            hide_index=True,
            width="stretch",
            column_config={
                "first_visit": st.column_config.DateColumn("First visit", format="YYYY-MM-DD")
            },
        )


# --------------------------------------------------------------------------
# Attribution — outside the tabs, so it shows on all three
# --------------------------------------------------------------------------

st.divider()
st.caption(ATTRIBUTION)
