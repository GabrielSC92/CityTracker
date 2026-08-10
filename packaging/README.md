# Packaging City Tracker for people who don't code

Produces `dist/CityTracker-Setup-<version>.exe` — a **66 MB** Windows installer
that a friend, or your dad, can double-click. It carries its own Python, so
there is nothing to install first, no PATH to fix, and no terminal to open.

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppVersion 1.0.0
powershell -ExecutionPolicy Bypass -File packaging\verify.ps1 -AppVersion 1.0.0
```

Build once, verify once, then send the file. `verify.ps1` installs the built
exe into a temp folder, launches it, checks the app really serves, uninstalls,
and confirms the travel history survived — 19 checks, all of which must pass
before you send anything to anyone.

## What a friend experiences

1. Double-clicks `CityTracker-Setup-1.0.0.exe`.
2. Windows warns that the publisher is unknown — see [Why Windows
   warns](#why-windows-warns-and-what-to-do-about-it), this is the one rough
   edge.
3. A normal Next → Install → Finish wizard, in English or Portuguese depending
   on their Windows language. **No administrator password**, no UAC prompt.
4. A **City Tracker** shortcut on the desktop and in the Start Menu.
5. Clicking it opens a small black window and then their browser, on their map.
   The window says, in plain words, to keep it open while using the app.
6. Their places are saved in `%LOCALAPPDATA%\CityTracker\data\city_tracker.db`.
   Backing up is still copying one file.

Uninstalling is normal Windows *Add or remove programs*. It removes the app and
**keeps the database** — reinstalling later finds every place still there.

## Requirements to build

| Need | Get it |
| --- | --- |
| Inno Setup 6 | `winget install JRSoftware.InnoSetup` (installs per-user, no admin) |
| 64-bit Python 3.13 | Any install; it resolves the wheels but is not shipped |

`build.ps1` finds Inno Setup in either the per-user or Program Files location.

## How it works

    build\payload\
      python\             Python's official embeddable distribution, unzipped
      lib\site-packages\  requirements, as wheels
      app\                app.py, db.py, geocode.py, continents.py, launcher.py
      icon.ico

The embeddable distribution ignores the machine's registry and PATH, so nothing
a friend installs later — another Python, a different version — can break the
installed copy. The shortcut runs `python\python.exe app\launcher.py`.

Three details are load-bearing, each of which cost a debugging round:

- **The vendor folder must be called `site-packages`.** Streamlit decides it is
  in "development mode" by looking for that word in its own `__file__`, and
  development mode refuses `--server.port` outright, which is how the launcher
  pins the app to a known address. `smoke_test.py` asserts against this.
- **`python313._pth` needs `import site`** plus the vendor path, or the
  embeddable runtime cannot see a single dependency.
- **The database lives outside the install folder.** `db.py` reads
  `CITY_TRACKER_DATA`, which the launcher points at the user's AppData. A
  checkout still uses its own `./data`, so your own map is untouched.

### Files

| File | Purpose |
| --- | --- |
| `build.ps1` | Downloads the runtime, vendors wheels, prunes, smoke-tests, compiles |
| `installer.iss` | The Inno Setup wizard: per-user, EN + PT-BR, shortcuts, uninstaller |
| `launcher.py` | Picks a port, starts Streamlit, opens the browser, owns the window |
| `smoke_test.py` | Run by the build with the *bundled* interpreter, before compiling |
| `verify.ps1` | Installs, launches, asserts, uninstalls the finished exe |
| `runtime-config.toml` | Streamlit settings for friends (the dev config is untouched) |
| `gen_icon.py` | Redraws `icon.ico`; only needed if you change the icon |
| `requirements-lock.txt` | Exactly what shipped, so a rebuild ships the same set |

### Versions

Builds use `requirements-lock.txt`, not `requirements.txt`, so a build next year
cannot silently ship an untested pandas. After deliberately upgrading something:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Unpinned -AppVersion 1.1.0
```

That re-resolves and rewrites the lock. Run the app from a checkout afterwards
and confirm it still behaves.

### Shipping a new version

Rebuild with a higher `-AppVersion` and send the new file. Because the `AppId`
in `installer.iss` stays the same, installing it upgrades in place rather than
making a second copy, and the database is untouched. Never change that `AppId`.

## Why Windows warns, and what to do about it

**You do not need a code-signing certificate.** Nothing here is blocked without
one. What happens unsigned:

- **Microsoft Defender SmartScreen** shows *"Windows protected your PC — unknown
  publisher"* on a downloaded exe with no reputation. Your friend clicks **More
  info → Run anyway**. That is the whole obstacle.
- **Defender's antivirus engine** is a different thing and rarely objects to an
  Inno Setup installer, which is one of the most common formats on Windows. (A
  PyInstaller one-file exe would be far more likely to trip a heuristic — one
  more reason this uses an installer.) A verified clean build here was neither
  blocked nor quarantined.
- **No UAC prompt at all**, because the install is per-user. Nobody has to find
  an administrator password.

Practical ways to make it painless, cheapest first:

1. **Tell them the click path in advance.** One line — *"Windows will say
   unknown publisher; click More info, then Run anyway"* — removes nearly all
   of the friction. A screenshot removes the rest.
2. **Share the file directly** (WhatsApp, Drive, WeTransfer) rather than from a
   web page. Reputation is per-file, so a file more of them run gets quieter
   over time on its own.
3. **Signing, if the warning still bothers you.** Be aware what it buys:
   - A standard **OV certificate** (~USD 200–400/year, and since 2023 the key
     must live on hardware or an HSM) replaces *"unknown publisher"* with your
     name — but SmartScreen reputation still accrues gradually, so early
     downloads can still get warned.
   - An **EV certificate** (~USD 400–700/year) is the one that gets immediate
     SmartScreen trust.
   - **Azure Artifact Signing** (formerly Trusted Signing) is USD 9.99/month
     and by far the cheapest legitimate route — but eligibility is regional:
     individuals in the **USA and Canada** only, organisations in the US,
     Canada, EU and UK. An individual in Brazil is not currently eligible.
   - A **self-signed certificate is worthless here.** Its root is not trusted,
     so SmartScreen treats it exactly like unsigned. Skip it.

For a handful of friends and family, option 1 is the right answer. Signing is
worth paying for when strangers download the app, not when you can text six
people a sentence.

If you do get a certificate, sign both the payload and the installer by adding
`SignTool` to `installer.iss` — Inno Setup's `SignTool` directive with
`sign=...` in its configuration.

## Known harmless log lines

Both appear in `%LOCALAPPDATA%\CityTracker\city-tracker.log`, never in the
user's window, and neither indicates a problem:

- `missing ScriptRunContext!` — normal when Streamlit's config is imported
  outside a page session.
- A `server.enableCORS` / `enableXsrfProtection` compatibility warning during
  startup. The resolved settings end up at Streamlit's secure defaults
  (`enableCORS=true`, XSRF protection on) and the server only listens on
  `127.0.0.1`.

## When something goes wrong on a friend's machine

The launcher window stays open on failure and names the log file. Ask them for
`%LOCALAPPDATA%\CityTracker\city-tracker.log` — the full Python traceback is in
there. Ports 8781–8800 are tried in order, so another app holding one is not a
problem.
