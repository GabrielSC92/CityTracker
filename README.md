# 🌍 City Tracker

A personal, offline-first map of everywhere you have been. Search for a place,
add it to your map, and everything is saved to a local SQLite file.

```
pip install -r requirements.txt
streamlit run app.py
```

## Giving it to someone who doesn't code

`packaging\build.ps1` produces a 66 MB Windows installer that carries its own
Python — no IDE, no `pip`, no terminal, and no administrator password needed at
the other end. A desktop shortcut starts the app and opens the browser.

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppVersion 1.0.0
powershell -ExecutionPolicy Bypass -File packaging\verify.ps1 -AppVersion 1.0.0
```

See [packaging/README.md](packaging/README.md) — including what to tell people
about the "unknown publisher" warning.

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

## Files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit UI — sidebar search/add/filter, map, table, stats |
| `geocode.py` | Photon + Nominatim search, merging and ranking |
| `db.py` | SQLite schema and queries |
| `continents.py` | Country code → continent, flag emoji |
