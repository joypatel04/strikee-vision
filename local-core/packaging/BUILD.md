# Running / packaging the Local Core on Windows

There are two ways to run on the venue's Windows box. For the field test, use
**Option A** — it's the reliable way to get YOLO + torch working.

## Option A (recommended): run from a Python environment

This runs the full product, including the live YOLO pipeline.

```bat
:: one-time setup
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[perception,desktop]"

:: run — opens a native window with the dashboard
strikee-core
```

- `strikee-core` starts the local server and opens a desktop window (pywebview).
  Without `[desktop]` it falls back to your default browser.
- The database is created next to where you run it (`strikee.db`); override with
  the `STRIKEE_DB` env var. Tick interval: `STRIKEE_TICK_SEC` (default 7).
- Configure a venue (cameras, assets, zones, sensors) via the dashboard `/docs`
  API, then start the pipeline from the dashboard.

Why this over a packaged .exe: PyInstaller + torch/OpenCV produces a
multi-gigabyte, fragile bundle. A venv is smaller, easier to update, and the
supported way to ship torch on Windows.

## Option B: build a Windows executable (dashboard + config only)

For a no-Python, double-click app **without** the live YOLO pipeline (useful for
config, review, analytics, and viewing a pipeline driven elsewhere):

```bat
.venv\Scripts\activate
pip install -e ".[build,desktop]"
pyinstaller packaging/strikee-core.spec
:: -> dist/StrikeeCore.exe
```

The spec deliberately excludes torch/cv2. To also package perception, remove the
`excludes` and add `--collect-all torch --collect-all ultralytics` — expect a
very large binary and test it on the target machine.

## Autostart

To launch on boot, add a shortcut to `strikee-core` (or `StrikeeCore.exe`) to
the Windows Startup folder (`shell:startup`).
