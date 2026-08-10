"""Start City Tracker for someone who only wants to look at their map.

On an installed machine there is no terminal, no PATH entry and no system-wide
Python — the shortcut hands this file to the interpreter bundled beside it. So
this script owns everything `streamlit run` normally leaves to a developer:
finding a free port, not starting a second copy on top of the first, waiting
for the server to actually answer, opening the browser, and keeping one window
around whose close button means "quit".

Streamlit's own chatter goes to a log file so the window stays readable; when
something breaks, the window stays open and says where that log is.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
MAIN_SCRIPT = APP_DIR / "app.py"
ICON = ROOT / "icon.ico"

# Deliberately away from Streamlit's default 8501 — a developer in the house
# should be able to run their own app without colliding with this one.
PORTS = range(8781, 8801)
STARTUP_TIMEOUT = 120.0
HEALTH_PATHS = ("/_stcore/health", "/healthz")

# Set by verify.ps1 so an automated launch test does not open a browser window.
NO_BROWSER = os.environ.get("CITY_TRACKER_NO_BROWSER") == "1"


def open_browser(url: str) -> None:
    if NO_BROWSER:
        print(f"  (browser suppressed) {url}")
        return
    webbrowser.open(url)


def user_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "CityTracker"


def bundled_python() -> Path:
    """The interpreter to run Streamlit with.

    Prefers the bundled runtime so a stray system Python can never be picked up
    by mistake; falls back to the current one when run from a checkout.
    """
    candidate = ROOT / "python" / "python.exe"
    return candidate if candidate.exists() else Path(sys.executable)


def is_healthy(port: int, timeout: float = 1.0) -> bool:
    """Is a Streamlit server answering on this port?

    The body has to say "ok", not merely return 200: Streamlit serves the single
    page app as a catch-all, so an unknown path answers 200 with the whole page
    and would make any running web server look like ours.
    """
    for path in HEALTH_PATHS:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=timeout
            ) as response:
                if response.status == 200 and response.read(16).strip() == b"ok":
                    return True
        except (urllib.error.URLError, OSError):
            continue
    return False


def already_running() -> int | None:
    """Return the port of a live City Tracker, if this is a second double-click.

    The port is read back from the file the previous launch wrote, rather than
    scanning, so another Streamlit app on a nearby port is never mistaken for
    ours.
    """
    marker = user_dir() / "runtime.json"
    try:
        port = int(json.loads(marker.read_text("utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if is_healthy(port) else None


def free_port() -> int:
    for port in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"Ports {PORTS.start}-{PORTS.stop - 1} are all busy on this computer."
    )


def dress_console(title: str) -> None:
    """Give the console window the app's name and icon. Cosmetic, never fatal."""
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
        window = ctypes.windll.kernel32.GetConsoleWindow()
        if window and ICON.exists():
            # LoadImageW(hInst, name, IMAGE_ICON, 0, 0, LR_LOADFROMFILE|LR_DEFAULTSIZE)
            handle = ctypes.windll.user32.LoadImageW(
                None, str(ICON), 1, 0, 0, 0x0010 | 0x0040
            )
            if handle:
                for size in (0, 1):  # ICON_SMALL, ICON_BIG
                    ctypes.windll.user32.SendMessageW(window, 0x0080, size, handle)
    except Exception:
        pass


def wait_until_serving(port: int, process: subprocess.Popen) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if is_healthy(port):
            return True
        time.sleep(0.4)
    return False


def start_streamlit(port: int, log_file) -> subprocess.Popen:
    command = [
        str(bundled_python()),
        "-m",
        "streamlit",
        "run",
        str(MAIN_SCRIPT),
        "--server.port",
        str(port),
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        "--server.fileWatcherType",
        "none",
        "--browser.gatherUsageStats",
        "false",
    ]
    environment = dict(os.environ)
    environment["CITY_TRACKER_DATA"] = str(user_dir() / "data")
    # Keeps Streamlit's first-run "enter your email" prompt from ever appearing.
    environment["STREAMLIT_SERVER_HEADLESS"] = "true"
    environment["PYTHONIOENCODING"] = "utf-8"

    return subprocess.Popen(
        command,
        cwd=str(APP_DIR),
        env=environment,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )


def hold_open(message: str) -> None:
    print(f"\n{message}")
    try:
        input("Press Enter to close this window. ")
    except EOFError:
        time.sleep(20)


def main() -> int:
    dress_console("City Tracker")
    home = user_dir()
    (home / "data").mkdir(parents=True, exist_ok=True)
    log = home / "city-tracker.log"

    print("  City Tracker")
    print("  ============\n")

    running = already_running()
    if running:
        print(f"  City Tracker is already open at http://localhost:{running}")
        print("  Bringing it up in your browser...")
        open_browser(f"http://localhost:{running}")
        time.sleep(2)
        return 0

    port = free_port()
    url = f"http://localhost:{port}"
    # Console output stays ASCII: this window inherits the machine's code page,
    # which is not UTF-8 on a stock Brazilian or US Windows install.
    print("  Starting up - your browser will open in a few seconds.\n")

    with open(log, "w", encoding="utf-8") as log_file:
        process = start_streamlit(port, log_file)
        try:
            if not wait_until_serving(port, process):
                hold_open(
                    "  City Tracker could not start.\n"
                    f"  Details were written to:\n    {log}"
                )
                return 1

            (home / "runtime.json").write_text(
                json.dumps({"port": port, "pid": process.pid}), encoding="utf-8"
            )
            open_browser(url)

            print(f"  City Tracker is running at {url}")
            print("  Your places are saved in:")
            print(f"    {home / 'data'}\n")
            print("  KEEP THIS WINDOW OPEN while you use the app.")
            print("  Closing it closes City Tracker.\n")
            process.wait()
            return process.returncode or 0
        except KeyboardInterrupt:
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            (home / "runtime.json").unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # A crash here must never be a window that blinks.
        hold_open(f"  City Tracker hit an unexpected problem:\n    {error}")
        sys.exit(1)
