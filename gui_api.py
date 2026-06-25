"""pywebview JS-API backend for the GameRater launcher UI.

An instance of Api is passed to webview.create_window(js_api=...), making
every public method callable from JS as window.pywebview.api.<name>(...).
"""

import os
import subprocess
import sys
import threading
import webbrowser

import appdata
from create_game_log_all_played_lists import run_all_played_lists
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

    # ── Config ──────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        return appdata.load_config(self.appdata_dir)

    def save_config(self, folder_url: str, master_url: str) -> dict:
        try:
            appdata.save_config(self.appdata_dir, folder_url.strip(), master_url.strip())
            return {'ok': True}
        except OSError as e:
            return {'ok': False, 'error': str(e)}

    def has_rater_page(self) -> bool:
        return appdata.get_html_path(self.appdata_dir).exists()

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

    # ── Navigation ──────────────────────────────────────────────────────

    def open_rater(self) -> dict:
        html_path = appdata.get_html_path(self.appdata_dir)
        if not html_path.exists():
            return {'ok': False, 'error': 'no rater page yet'}
        webbrowser.open(html_path.as_uri())
        return {'ok': True}

    def open_launcher(self) -> dict:
        if not self.window:
            return {'ok': False, 'error': 'no window'}
        launcher_path = appdata.get_bundle_dir() / 'assets' / 'launcher.html'
        self.window.load_url(str(launcher_path))
        return {'ok': True}

    # ── Save from rater page ───────────────────────────────────────────

    def save_csv(self, csv_text: str) -> dict:
        try:
            appdata.get_csv_path(self.appdata_dir).write_text(csv_text, encoding='utf-8')
            return {'ok': True}
        except OSError as e:
            return {'ok': False, 'error': str(e)}

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
