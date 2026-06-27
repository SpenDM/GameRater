#!/usr/bin/env python3
"""GameRater desktop app entry point.

Opens a pywebview window showing the launcher screen (assets/launcher.html),
which lets the user configure Backloggd URLs, run the scraping scripts, and
jump to the generated rater page (gamelog.html) — all backed by the Api
class in gui_api.py.
"""

import webview

import appdata
from gui_api import Api


def main():
    api = Api()
    bundle = appdata.get_bundle_dir()
    # Make sure the rater page exists before the window's iframe loads it.
    api.ensure_rater_page()
    # Load the launcher from AppData (not the bundle) so it shares a directory
    # with the generated rater page; pywebview roots its HTTP server at this
    # directory and can then serve gamelog.html and its covers/images too.
    launcher_path = appdata.get_launcher_path(api.appdata_dir)
    icon_path = bundle / 'assets' / 'GameRaterLogo.ico'
    window = webview.create_window(
        'GameRater',
        url=str(launcher_path),
        js_api=api,
        width=1280,
        height=820,
        min_size=(900, 600),
        fullscreen=True,
    )
    api.window = window
    webview.start(icon=str(icon_path) if icon_path.exists() else None)


if __name__ == '__main__':
    main()
