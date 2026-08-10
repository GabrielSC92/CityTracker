# 🌍 City Tracker

A personal, offline-first map of everywhere you have been. Search for a place,
add it to your map, and everything is saved to a local SQLite file.

## Install

**Windows, with no Python and no terminal** — [download the latest
installer](https://github.com/GabrielSC92/CityTracker/releases/latest) and
double-click it. It carries its own Python, installs per-user without an
administrator password, and leaves a desktop shortcut that starts the app and
opens your browser.

Windows will warn that the publisher is unknown, because the installer is not
code-signed. Click **More info → Run anyway**; that is the whole obstacle. See
[why Windows warns](packaging/README.md#why-windows-warns-and-what-to-do-about-it)
for why a certificate is not worth buying to reassure six friends.

**From source**, on any platform:

```
pip install -r requirements.txt
streamlit run app.py
```

## Giving it to someone who doesn't code

`packaging\build.ps1` produces the 66 MB installer described above, so you can
build and hand over a version of your own rather than sending them a link.

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppVersion 1.0.0
powershell -ExecutionPolicy Bypass -File packaging\verify.ps1 -AppVersion 1.0.0
```

See [packaging/README.md](packaging/README.md) for how the payload is assembled,
the three layout details that are load-bearing, and what `verify.ps1` checks
before you send anything to anyone.

## Feature search

The headline feature: you remember **Puy du Fou** but not the town it sits in.
Type it, and the search comes back with the town attached — *Les Épesses, Pays
de la Loire, France* — so you can pick the right one and add it.

Two free, key-less OpenStreetMap providers are queried and merged:

| Provider | Why it's there |
| --- | --- |
| **Photon** (`photon.komoot.io`) | Forgiving fuzzy/prefix matching for half-remembered names |
| **Nominatim** (`nominatim.openstreetmap.org`) | Authoritative address breakdown down to city / region / country |

Because both are OpenStreetMap-backed, hits dedupe on `(osm_type, osm_id)` and
blank fields from one provider are filled in from the other. If one service is
down the search degrades to a warning and keeps working on the other.

On top of the raw results the search:

- **Normalises accents and punctuation**, so `Puy-du-Fou`, `puy du fou` and
  `Puy du Fou` all match equally.
- **Merges near-duplicates.** OSM stores most towns twice — as a place node
  *and* as an administrative boundary. Same name, same country, within 15 km is
  treated as one place.
- **Ranks by name similarity, not fame.** Nominatim's importance metric buries
  small towns under famous namesakes; weighting the literal name match puts
  `Cachoeirinha`-the-town back on top. Landmarks, parks and settlements get a
  boost; information boards, bus stops and street segments get demoted.
- **Labels things usefully.** A city is reported as `City` rather than OSM's
  raw `boundary/administrative`.

Small towns work exactly like landmarks — searching `Cachoeirinha` returns the
Rio Grande do Sul, Pernambuco and Tocantins municipalities as separate,
clearly-labelled options.

Nominatim's usage policy (identifying `User-Agent`, max 1 request/second) is
honoured by a throttle in `geocode.py`. Results are cached for an hour.

## What you can do

- **Map** — markers coloured by status (✅ visited / ⭐ wishlist), with popups
  showing the city, date, rating and notes. Light / dark / street basemaps,
  optional clustering, fullscreen.
- **Places** — an editable table. Change the name, status, date, rating and
  notes inline, tick rows to delete, export everything to CSV.
- **Stats** — places by continent and country, places per year, and a
  per-country summary with first-visit dates.
- **Filters** — by status, continent and country, applied across all three tabs.
- **Manual add** — for anywhere OSM doesn't know about, enter a name and
  coordinates directly.

## Roadmap

Four things are planned. The order below is the order they should be built —
profiles reshape the schema, so doing them before bulk import saves migrating
the same rows twice.

| # | Feature | Touches |
| --- | --- | --- |
| 1 | [Visual overhaul](#1-visual-overhaul) | `app.py`, `.streamlit/config.toml` |
| 2 | [Login with profiles](#2-login-with-profiles) | `db.py`, `app.py`, new `auth.py` |
| 3 | [Easy import of data](#3-easy-import-of-data) | new `importers.py`, `geocode.py` |
| 4 | [H3 statistics](#4-h3-statistics) | new `hexes.py`, `app.py` stats tab |

### 1. Visual overhaul

Today the app is stock Streamlit with a green `primaryColor`. The goal is
something that looks deliberate rather than default.

- **A real theme** — full palette in `.streamlit/config.toml` (background,
  secondary background, text, font) instead of the single accent colour, plus a
  light/dark switch that also drives the basemap so the map stops fighting the
  page.
- **Header metrics as cards.** The four `st.metric` counters become a designed
  row — flag strip for countries, a share-of-world figure, sparkline of places
  per year.
- **Better markers.** `folium.Icon` gives every marker the same Font Awesome
  pin; switch to per-category glyphs (mountain, park, theme park, city) sized by
  rating, with the popup HTML in `app.py` moved into a small template.
- **Layout.** Sidebar is doing search, manual add *and* filters at once; move
  filters onto a compact bar above the tabs so the map gets the full width.
- **Empty and first-run states** worth looking at, since a fresh install has an
  empty map.

### 2. Login with profiles

One database currently means one traveller. Profiles let a household or a couple
keep separate maps in the same install, and compare them.

- **Schema.** New `profiles` table (`id`, `name`, `avatar`, `created_at`) and a
  `profile_id` foreign key on `places`.
- **The dedupe index has to change.** `idx_places_osm` is unique on
  `(osm_type, osm_id)` across the whole file, so as soon as there are two
  profiles the second person cannot add a place the first one already has. It
  becomes unique on `(profile_id, osm_type, osm_id)`, which needs a migration —
  the schema is currently create-only, so a `schema_version` table and a
  migration step come with this.
- **Auth.** Two different environments to serve: the packaged Windows build is a
  single-machine app where a PIN or a plain profile picker is enough, while a
  hosted deployment wants real accounts (`st.login` / OIDC, or
  `streamlit-authenticator` with hashed passwords). Keep the check behind
  `auth.py` so the storage layer only ever sees a `profile_id`.
- **Sharing.** Read-only view of another profile's map, and a compare mode —
  who has been where, what is on both wishlists.
- **Filters and export** become profile-scoped; the CSV export gains a
  `profile` column.

### 3. Easy import of data

Export exists, import does not, so the only way in is one place at a time
through the search box. That is the biggest barrier to actually using the app
with a travel history that already exists somewhere else.

- **Formats.** CSV and Excel first, then JSON/GeoJSON, GPX and KML (what phones
  and GPS apps hand you), and Google Maps Takeout saved-place lists.
- **Column mapping UI.** Upload, preview the first rows, map columns onto
  `name` / `city` / `country` / `lat` / `lon` / `status` / `visited_on` /
  `rating` / `notes`, with a guess pre-filled from the header names. Remember
  the mapping so re-importing an updated file is one click.
- **Rows without coordinates** get geocoded through the existing Photon +
  Nominatim path. Nominatim's 1 request/second throttle in `geocode.py` makes a
  400-row file a 7-minute job, so this needs batching, a progress bar and a
  resumable queue rather than a blocking call.
- **Ambiguity queue.** Where the geocoder returns several plausible matches,
  park the row and let the user pick afterwards instead of guessing.
- **Dry run.** Report how many rows are new, how many duplicate an existing OSM
  feature, and how many failed to resolve — before writing anything.

### 4. H3 statistics

Counting by country is coarse: a fortnight across Île-de-France and a fortnight
across Brazil both read as "1 country". Binning places into
[H3](https://h3geo.org) hexagons gives an even-area view of where you actually
spend time.

- **Store the cell.** An `h3_cell` column filled at insert time from
  `lat`/`lon`, or computed on load — cheap enough either way at this data size.
- **Hex map.** A `pydeck` `H3HexagonLayer` coloured by count, with a resolution
  slider so the same data reads as continents at low resolution and
  neighbourhoods at high.
- **Stats the country grouping cannot express** — how much of the world is
  covered at a given resolution, densest cells, nearest unvisited cell, cells
  added per year as a time series.
- **New dependencies.** `h3` and `pydeck`, which means regenerating
  `packaging/requirements-lock.txt` and re-checking the installer size claim in
  this README.

## Storage

Everything lives in `data/city_tracker.db`. Backing up your travel history is
just copying that one file. The schema is created on first run.

| Column | Notes |
| --- | --- |
| `name`, `city`, `state`, `country`, `country_code`, `continent` | Continent is derived from the country code |
| `lat`, `lon` | Map position |
| `osm_type`, `osm_id` | Unique index — the same real place can't be added twice |
| `status` | `visited` or `wishlist` |
| `visited_on`, `rating`, `notes` | Yours to edit |
| `category`, `feature_type` | OSM classification, e.g. `tourism` / `theme_park` |

Only `name`, `status`, `visited_on`, `rating` and `notes` are editable from the
table; geographic fields stay as the geocoder resolved them.

## Licensing and attribution

The code is MIT (see [LICENSE](LICENSE)). The place data is not ours: it comes
from OpenStreetMap via Photon and Nominatim, and OSM licenses its database under
the [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

Two obligations follow, and both are met:

- **Credit where the data is shown.** The basemaps carry Leaflet's built-in
  attribution inside the map, but the Places and Stats tabs show geocoded fields
  with no map on screen, so `ATTRIBUTION` in `app.py` is also rendered as a
  page footer on every tab.
- **Identify yourself to Nominatim.** `geocode.py` sends a descriptive
  `User-Agent` and throttles to 1 request/second, per their
  [usage policy](https://operations.osmfoundation.org/policies/nominatim/).

**ODbL share-alike does not reach this project, and does not affect the MIT
licence on the code.** Share-alike applies when you publicly distribute a
database derived from OSM. Nothing here does: the installer payload is the four
`.py` files plus the Python runtime and wheels, and `data/city_tracker.db` is
created empty on first run. The only OSM-derived database is the one on your own
machine, holding your own places, which you never publish.

If you *do* publish an export, the CSV is your Produced Work and the credit
becomes yours to give — `© OpenStreetMap contributors (ODbL)` alongside it is
enough. The export itself is left as clean CSV with no comment header, so it
stays round-trippable by the planned importer and opens cleanly in Excel.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit UI — sidebar search/add/filter, map, table, stats |
| `geocode.py` | Photon + Nominatim search, merging and ranking |
| `db.py` | SQLite schema and queries |
| `continents.py` | Country code → continent, flag emoji |
