"""Prove the staged bundle works before it becomes an installer.

Run by build.ps1 with the *bundled* interpreter, which is the only one that can
answer the question that matters: can a machine with no Python, no PATH entry
and no compiler run this app? Every failure here is a failure a friend would
have hit instead.

    python.exe smoke_test.py <staged app dir>
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: smoke_test.py <staged app dir>", file=sys.stderr)
        return 2

    app_dir = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(app_dir))

    # Third-party imports first: these are the ones the embeddable runtime has
    # to find through the patched ._pth, and pyarrow/numpy are the ones whose
    # compiled extensions fail loudly if the wheel and runtime disagree.
    import folium
    import pandas
    import pyarrow
    import requests
    import sqlite3
    import ssl
    import streamlit
    import streamlit_folium

    print(f"  python     {sys.version.split()[0]}")
    print(f"  streamlit  {streamlit.__version__}")
    print(f"  pandas     {pandas.__version__}")
    print(f"  pyarrow    {pyarrow.__version__}")
    print(f"  folium     {folium.__version__}")
    print(f"  sqlite3    {sqlite3.sqlite_version}")
    print(f"  tls        {ssl.OPENSSL_VERSION.split()[1]}")
    assert requests and streamlit_folium  # imported for their side effects only

    # Streamlit infers "development mode" from the absence of site-packages in
    # its own path, and development mode rejects --server.port, which is how the
    # launcher pins the app to a known address. Cheap assertion, whole-app bug.
    import streamlit.config

    development_mode = streamlit.config.get_option("global.developmentMode")
    assert not development_mode, (
        "Streamlit resolved global.developmentMode=True, so it will refuse "
        f"--server.port. Its path is {Path(streamlit.__file__).parent}, which "
        "needs a 'site-packages' component."
    )
    print("  streamlit  not in development mode (accepts --server.port)")

    # Then the app's own modules, against a throwaway database, so a broken
    # schema or a missing file is caught here rather than on someone's desktop.
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["CITY_TRACKER_DATA"] = scratch
        for module in ("continents", "geocode", "db"):
            __import__(module)

        import continents
        import db

        db.init_db()
        row_id, created = db.add_place(
            name="Puy du Fou",
            lat=46.8907,
            lon=-0.9302,
            city="Les Epesses",
            country="France",
            country_code="FR",
            osm_type="way",
            osm_id=1,
        )
        assert created and row_id, "insert did not create a row"
        places = db.load_places()
        assert len(places) == 1, f"expected 1 place, got {len(places)}"
        assert places.iloc[0]["continent"] == continents.continent_for("FR")
        assert db.delete_places([row_id]) == 1, "delete did not remove the row"
        assert (Path(scratch) / "city_tracker.db").exists(), "no database written"
        print("  database   schema + insert/read/delete OK")

        # Finally run the real script the way a browser session would, so a
        # dependency that imports fine but breaks at render time (a pandas or
        # Streamlit major bump, say) fails the build instead of the friend.
        from streamlit.testing.v1 import AppTest

        session = AppTest.from_file(str(app_dir / "app.py"), default_timeout=180)
        session.run()
        assert not session.exception, "app.py raised: " + "; ".join(
            str(item.value) for item in session.exception
        )
        assert len(session.tabs) == 3, f"expected 3 tabs, rendered {len(session.tabs)}"
        print(f"  app.py     renders {len(session.tabs)} tabs, no exceptions")

    return 0


if __name__ == "__main__":
    sys.exit(main())
