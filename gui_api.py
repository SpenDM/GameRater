"""pywebview JS-API backend for the GameRater launcher UI.

An instance of Api is passed to webview.create_window(js_api=...), making
every public method callable from JS as window.pywebview.api.<name>(...).
"""

import base64
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

_SAVE_SERVER_PORT = 57432


def _make_save_handler(appdata_dir):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

        def do_POST(self):
            if self.path != '/save-csv':
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            try:
                appdata.get_csv_path(appdata_dir).write_text(body, encoding='utf-8')
                self._respond(200, b'{"ok":true}')
                try:
                    rebuild_html_from_csv(
                        str(appdata.get_csv_path(appdata_dir)),
                        str(appdata.get_covers_dir(appdata_dir)),
                        str(appdata.get_html_path(appdata_dir)),
                    )
                except Exception:
                    pass
            except Exception as e:
                self._respond(500, json.dumps({'ok': False, 'error': str(e)}).encode())

        def _respond(self, code, body):
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass
    return Handler

import appdata
from create_game_log_all_played_lists import rebuild_html_from_csv, run_all_played_lists
from create_game_log_current_year import run_current_year
from create_game_log_historic import run_historic

_status_lock = threading.Lock()
_status = {'running': False, 'op': None, 'log': [], 'done': True, 'error': None, 'result': None}
_chromium_ready = False


def _reset_status(op: str) -> None:
    with _status_lock:
        _status.update({'running': True, 'op': op, 'log': [], 'done': False, 'error': None, 'result': None})


def _append_log(msg: str) -> None:
    with _status_lock:
        _status['log'].append(msg)


def _finish(result: dict | None = None, error: str | None = None) -> None:
    with _status_lock:
        _status['running'] = False
        _status['done'] = True
        _status['result'] = result
        _status['error'] = error


class Api:
    def __init__(self) -> None:
        self.window = None
        self.appdata_dir = appdata.ensure_appdata_initialized()
        if getattr(sys, 'frozen', False):
            browsers_dir = os.path.join(self.appdata_dir, 'playwright-browsers')
            os.makedirs(browsers_dir, exist_ok=True)
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = browsers_dir
        try:
            server = http.server.HTTPServer(
                ('127.0.0.1', _SAVE_SERVER_PORT), _make_save_handler(self.appdata_dir)
            )
            threading.Thread(target=server.serve_forever, daemon=True).start()
        except OSError:
            pass  # port already in use (second instance or other app)

    # ── Config ──────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        return appdata.load_config(self.appdata_dir)

    def save_config(self, folder_url: str, master_url: str) -> dict:
        try:
            appdata.save_config(self.appdata_dir, folder_url.strip(), master_url.strip())
            return {'ok': True}
        except OSError as e:
            return {'ok': False, 'error': str(e)}

    # ── Scrape operations ──────────────────────────────────────────────

    def start_current_year(self) -> dict:
        return self._start('current_year', self._run_current_year_worker)

    def start_all_played_lists(self) -> dict:
        return self._start('all_played_lists', self._run_all_played_lists_worker)

    def start_historic(self) -> dict:
        return self._start('historic', self._run_historic_worker)

    def _start(self, op: str, worker) -> dict:
        with _status_lock:
            if _status['running']:
                return {'ok': False, 'error': 'busy'}
        _reset_status(op)
        threading.Thread(target=worker, daemon=True).start()
        return {'ok': True}

    def get_status(self) -> dict:
        with _status_lock:
            return dict(_status, log=list(_status['log']))

    # ── Rater page / window ─────────────────────────────────────────────

    def ensure_rater_page(self) -> dict:
        """Rebuild gamelog.html from the CSV (covers-only, no network) so the
        rater iframe always has a page to show with the latest template/JS.
        Called at startup before the window loads."""
        try:
            rebuild_html_from_csv(
                str(appdata.get_csv_path(self.appdata_dir)),
                str(appdata.get_covers_dir(self.appdata_dir)),
                str(appdata.get_html_path(self.appdata_dir)),
            )
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def toggle_fullscreen(self) -> dict:
        if not self.window:
            return {'ok': False, 'error': 'no window'}
        self.window.toggle_fullscreen()
        return {'ok': True}

    def quit_app(self) -> dict:
        if self.window:
            self.window.destroy()
        return {'ok': True}

    def export_image(self, data_url: str, view: str, year) -> dict:
        """Save a base64 PNG data URL (produced by html2canvas in the rater
        page) to the user's Downloads folder. Returns the saved path."""
        try:
            if not data_url or ',' not in data_url:
                return {'ok': False, 'error': 'no image data'}
            png_bytes = base64.b64decode(data_url.split(',', 1)[1])

            downloads = Path.home() / 'Downloads'
            downloads.mkdir(parents=True, exist_ok=True)

            kind = 'GOTY' if view == 'goty' else 'Tiers'
            year_str = re.sub(r'[^0-9A-Za-z]', '', str(year)) or 'export'
            base = f'GameRater_{kind}_{year_str}'
            dest = downloads / f'{base}.png'
            n = 2
            while dest.exists():
                dest = downloads / f'{base}_{n}.png'
                n += 1

            dest.write_bytes(png_bytes)
            return {'ok': True, 'path': str(dest), 'name': dest.name}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def open_external(self, url: str) -> dict:
        url = (url or '').strip()
        if not (url.startswith('http://') or url.startswith('https://')):
            return {'ok': False, 'error': 'invalid url'}
        webbrowser.open(url)
        return {'ok': True}

    # ── Save from rater page ───────────────────────────────────────────

    def save_csv(self, csv_text: str) -> dict:
        try:
            appdata.get_csv_path(self.appdata_dir).write_text(csv_text, encoding='utf-8')
            threading.Thread(target=self._rebuild_html, daemon=True).start()
            return {'ok': True}
        except OSError as e:
            return {'ok': False, 'error': str(e)}

    def _rebuild_html(self) -> None:
        try:
            rebuild_html_from_csv(
                str(appdata.get_csv_path(self.appdata_dir)),
                str(appdata.get_covers_dir(self.appdata_dir)),
                str(appdata.get_html_path(self.appdata_dir)),
            )
        except Exception:
            pass

    # ── Chromium auto-install ──────────────────────────────────────────

    def _ensure_chromium(self, log) -> bool:
        global _chromium_ready
        if _chromium_ready:
            return True
        log("Checking Playwright browser install (first run may take a minute)...")
        try:
            if getattr(sys, 'frozen', False):
                from playwright._impl._driver import compute_driver_executable, get_driver_env
                driver_executable, driver_cli = compute_driver_executable()
                proc = subprocess.run(
                    [str(driver_executable), str(driver_cli), 'install', 'chromium'],
                    capture_output=True, text=True, timeout=600, env=get_driver_env(),
                )
            else:
                proc = subprocess.run(
                    [sys.executable, '-m', 'playwright', 'install', 'chromium'],
                    capture_output=True, text=True, timeout=600,
                )
            if proc.returncode != 0:
                log(f"  ⚠ Browser install failed: {proc.stderr[-500:]}")
                return False
            _chromium_ready = True
            log("  Browser ready.")
            return True
        except Exception as e:
            log(f"  ⚠ Browser install failed: {e}")
            return False

    # ── Workers (run on background threads) ────────────────────────────

    def _run_in_appdata(self, fn) -> None:
        """Run fn() with CWD set to the AppData dir, so the existing scripts'
        relative 'games.csv' / 'gamelog.html' / 'covers' paths land there.

        fn() is expected to call _finish() itself on every path (success,
        handled failure). As a last-resort safety net, ANY exception that
        escapes fn() (or this chdir wrapper itself) is also turned into a
        _finish(error=...) call — otherwise the background thread would die
        silently (Python doesn't propagate thread exceptions anywhere
        visible, and the frozen exe has no console to print them to), and
        the launcher would be left polling a 'running: true' status forever
        with no error ever shown.
        """
        try:
            prev_cwd = os.getcwd()
            try:
                os.chdir(self.appdata_dir)
                fn()
            finally:
                os.chdir(prev_cwd)
        except Exception as e:
            with _status_lock:
                already_done = _status['done']
            if not already_done:
                _finish(error=str(e))

    def _run_current_year_worker(self) -> None:
        def body():
            if not self._ensure_chromium(_append_log):
                _finish(error='Could not install the Playwright browser.')
                return
            config = appdata.load_config(self.appdata_dir)
            result = run_current_year('games.csv', 'gamelog.html', config['folder_url'],
                                       progress_cb=_append_log)
            _finish(result=result)
        self._run_in_appdata(body)

    def _run_all_played_lists_worker(self) -> None:
        def body():
            if not self._ensure_chromium(_append_log):
                _finish(error='Could not install the Playwright browser.')
                return
            config = appdata.load_config(self.appdata_dir)
            result = run_all_played_lists('games.csv', 'gamelog.html', config['folder_url'],
                                           progress_cb=_append_log)
            _finish(result=result)
        self._run_in_appdata(body)

    def _run_historic_worker(self) -> None:
        def body():
            if not self._ensure_chromium(_append_log):
                _finish(error='Could not install the Playwright browser.')
                return
            config = appdata.load_config(self.appdata_dir)
            result = run_historic('games.csv', 'gamelog.html', config['master_url'],
                                   progress_cb=_append_log)
            _finish(result=result)
        self._run_in_appdata(body)
