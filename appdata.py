"""Per-user AppData storage for the GameRater desktop app.

All files the app reads/writes at runtime (games.csv, gamelog.html, covers/,
config.json) live under %LOCALAPPDATA%\\GameRater so the app works the same
no matter where the .exe is launched from. Bundled read-only assets
(launcher.html, the rating-tier images, a starter cover cache) ship alongside
the app/exe and are copied into AppData on first run only.
"""

import json
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "GameRater"

DEFAULT_FOLDER_URL = 'https://backloggd.com/u/smorrs/lists/folder/games-played-by-year/'
DEFAULT_MASTER_URL = 'https://backloggd.com/u/smorrs/games/'


def get_appdata_dir() -> Path:
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(base) / APP_NAME


def get_bundle_dir() -> Path:
    """Directory containing read-only bundled assets (launcher.html, images/, covers/)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def get_csv_path(appdata_dir: Path) -> Path:
    return appdata_dir / 'games.csv'


def get_html_path(appdata_dir: Path) -> Path:
    return appdata_dir / 'gamelog.html'


def get_covers_dir(appdata_dir: Path) -> Path:
    return appdata_dir / 'covers'


def get_config_path(appdata_dir: Path) -> Path:
    return appdata_dir / 'config.json'


def get_launcher_path(appdata_dir: Path) -> Path:
    return appdata_dir / 'launcher.html'


def ensure_appdata_initialized() -> Path:
    """Create the AppData dir and seed it with default assets on first run."""
    appdata = get_appdata_dir()
    appdata.mkdir(parents=True, exist_ok=True)
    bundle = get_bundle_dir()

    images_dir = appdata / 'images'
    if not images_dir.exists():
        bundled_images = bundle / 'assets' / 'images'
        if bundled_images.exists():
            shutil.copytree(bundled_images, images_dir)
        else:
            images_dir.mkdir(parents=True, exist_ok=True)

    covers_dir = get_covers_dir(appdata)
    if not covers_dir.exists():
        covers_dir.mkdir(parents=True, exist_ok=True)
        bundled_covers = bundle / 'assets' / 'covers'
        if bundled_covers.exists():
            shutil.copytree(bundled_covers, covers_dir, dirs_exist_ok=True)

    logo_path = appdata / 'GameRaterLogo.png'
    if not logo_path.exists():
        bundled_logo = bundle / 'assets' / 'GameRaterLogo.png'
        if bundled_logo.exists():
            shutil.copy2(bundled_logo, logo_path)

    # The launcher must live alongside the generated rater page (gamelog.html)
    # so pywebview's HTTP server roots itself here and can serve both. Copy it
    # fresh on every launch so app upgrades pick up launcher.html changes.
    bundled_launcher = bundle / 'assets' / 'launcher.html'
    if bundled_launcher.exists():
        shutil.copy2(bundled_launcher, get_launcher_path(appdata))

    # html2canvas powers the rater page's "Export Image" feature. Copy it
    # fresh each launch (alongside gamelog.html) so it's served same-origin by
    # pywebview's HTTP server and picks up any bundled upgrade.
    bundled_html2canvas = bundle / 'assets' / 'html2canvas.min.js'
    if bundled_html2canvas.exists():
        shutil.copy2(bundled_html2canvas, appdata / 'html2canvas.min.js')

    games_csv = get_csv_path(appdata)
    if not games_csv.exists():
        bundled_csv = bundle / 'assets' / 'games.csv'
        if bundled_csv.exists():
            shutil.copy2(bundled_csv, games_csv)
        else:
            games_csv.write_text(
                'title,rating,review,url,year_played,release_year,goty_categories\n',
                encoding='utf-8',
            )

    config_path = get_config_path(appdata)
    if not config_path.exists():
        save_config(appdata, DEFAULT_FOLDER_URL, DEFAULT_MASTER_URL)

    return appdata


def load_config(appdata_dir: Path) -> dict:
    config_path = get_config_path(appdata_dir)
    if not config_path.exists():
        return {'folder_url': DEFAULT_FOLDER_URL, 'master_url': DEFAULT_MASTER_URL}
    try:
        data = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'folder_url': DEFAULT_FOLDER_URL, 'master_url': DEFAULT_MASTER_URL}
    return {
        'folder_url': data.get('folder_url') or DEFAULT_FOLDER_URL,
        'master_url': data.get('master_url') or DEFAULT_MASTER_URL,
    }


def save_config(appdata_dir: Path, folder_url: str, master_url: str) -> None:
    config_path = get_config_path(appdata_dir)
    config_path.write_text(
        json.dumps({'folder_url': folder_url, 'master_url': master_url}, indent=2),
        encoding='utf-8',
    )
