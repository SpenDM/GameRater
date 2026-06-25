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
    launcher_path = bundle / 'assets' / 'launcher.html'
    icon_path = bundle / 'assets' / 'GameRaterLogo.ico'
    window = webview.create_window(
        'GameRater',
        url=str(launcher_path),
        js_api=api,
        width=900,
        height=820,
        min_size=(700, 600),
    )
    api.window = window
    webview.start(icon=str(icon_path) if icon_path.exists() else None)


if __name__ == '__main__':
    main()
