#!/usr/bin/env python3
"""Firestore-backed Backloggd scraper for the GameRater web app.

Invoked by .github/workflows/scrape.yml (workflow_dispatch) with a user id and
a mode. Reads the user's Backloggd URLs + existing games from Firestore, runs
the same Playwright scraping the desktop app used, and writes the merged games
(and a live progress `status`) back to Firestore.

Reuses the proven low-level scraping/merge functions from the repo-root scripts;
only the sinks change (CSV/HTML/local covers → Firestore + remote cover URLs).

Env:
  SCRAPE_UID                 Firebase uid of the user to scrape for
  SCRAPE_MODE                current_year | all_played_lists | historic
  FIREBASE_SERVICE_ACCOUNT   service-account JSON (string)
"""
import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

# Reuse the existing scraper functions (kept at the repo root for the desktop app).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from create_game_log_all_played_lists import (  # noqa: E402
    fetch_year_lists,
    fetch_backloggd_list,
    fetch_release_years,
    merge_list_into_games,
)
from create_game_log_historic import merge_master_list_into_games  # noqa: E402

from google.cloud import firestore  # noqa: E402
from google.oauth2 import service_account  # noqa: E402

DEFAULT_FOLDER_URL = 'https://backloggd.com/u/smorrs/lists/folder/games-played-by-year/'
DEFAULT_MASTER_URL = 'https://backloggd.com/u/smorrs/games/'


def get_client() -> firestore.Client:
    info = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
    creds = service_account.Credentials.from_service_account_info(info)
    return firestore.Client(project=info['project_id'], credentials=creds)


# ── Web ⇄ internal game format conversion ────────────────────────────────────
def web_to_internal(games_web):
    """Firestore game docs → the {title,...,goty_categories} dicts the scraper
    functions expect. Returns (games, cover_map[title]=cover_url)."""
    games, cover_map = [], {}
    for g in games_web or []:
        title = (g.get('title') or '').strip()
        if not title:
            continue
        cats = g.get('categories') or []
        cats_str = ';'.join(cats) if isinstance(cats, list) else str(cats or '')
        games.append({
            'title': title,
            'rating': (g.get('rating') or 'unrated'),
            'review': g.get('review') or '',
            'url': g.get('url') or '',
            'year_played': str(g.get('year_played') or ''),
            'release_year': str(g.get('release_year') or ''),
            'goty_categories': cats_str,
        })
        if g.get('cover'):
            cover_map[title] = g['cover']
    return games, cover_map


def internal_to_web(games, cover_map):
    out = []
    for g in games:
        cats = [c for c in (g.get('goty_categories') or '').split(';') if c]
        out.append({
            'title': g['title'],
            'rating': g.get('rating') or 'unrated',
            'review': g.get('review') or '',
            'url': g.get('url') or '',
            'year_played': g.get('year_played') or '',
            'release_year': g.get('release_year') or '',
            'cover': cover_map.get(g['title'], ''),
            'categories': cats,
        })
    return out


# ── Live progress status (written to users/{uid}.status) ─────────────────────
class Status:
    def __init__(self, user_ref, op):
        self.ref = user_ref
        self.op = op
        self.lines = []
        self._last = 0.0

    def _write(self, extra):
        data = {
            'op': self.op,
            'log': self.lines[-40:],
            'updatedAt': int(time.time() * 1000),
            'running': extra.get('running', True),
            'done': extra.get('done', False),
            'error': extra.get('error'),
        }
        for k in ('added', 'covers_found', 'total'):
            if k in extra:
                data[k] = extra[k]
        self.ref.set({'status': data}, merge=True)

    def start(self, msg=None):
        if msg:
            self.lines.append(msg)
        self._write({'running': True, 'done': False})

    def log(self, msg):
        print(msg, flush=True)
        self.lines.append(str(msg))
        now = time.time()
        if now - self._last > 1.2:   # throttle Firestore writes
            self._last = now
            self._write({'running': True, 'done': False})

    def done(self, **kw):
        self._write({'running': False, 'done': True, **kw})

    def fail(self, err):
        self.lines.append(f'Error: {err}')
        self._write({'running': False, 'done': True, 'error': str(err)})


def run(client, uid, mode, status):
    user_ref = client.document(f'users/{uid}')
    games_ref = client.document(f'users/{uid}/data/games')

    config = (user_ref.get().to_dict() or {}).get('config') or {}
    folder_url = config.get('folder_url') or DEFAULT_FOLDER_URL
    master_url = config.get('master_url') or DEFAULT_MASTER_URL

    games_web = (games_ref.get().to_dict() or {}).get('games') or []
    games, cover_map = web_to_internal(games_web)
    status.start(f'Found {len(games)} existing game(s).')
    log = status.log

    all_cover_urls, all_page_urls, added_total = {}, {}, 0

    if mode in ('current_year', 'all_played_lists'):
        log('Discovering year lists from Backloggd folder...')
        year_lists = asyncio.run(fetch_year_lists(folder_url))
        if mode == 'current_year':
            year_lists = year_lists[:1]
            if year_lists:
                log(f'Using most recent year list: {year_lists[0][0]}')
        for year, list_url in year_lists:
            log(f'Fetching games for {year}...')
            entries = asyncio.run(fetch_backloggd_list(list_url))
            if not entries:
                log(f'  Could not fetch list for {year}.')
                continue
            games, added = merge_list_into_games(games, entries, year=year)
            if added:
                log(f'  Added {added} new game(s) for {year}.')
                added_total += added
            all_cover_urls.update({e['title']: e['cover_url'] for e in entries if e.get('cover_url')})
            all_page_urls.update({e['title']: e['page_url'] for e in entries if e.get('page_url')})

    elif mode == 'historic':
        log('Fetching full game library from Backloggd...')
        entries = asyncio.run(fetch_backloggd_list(master_url))
        all_cover_urls.update({e['title']: e['cover_url'] for e in entries if e.get('cover_url')})
        all_page_urls.update({e['title']: e['page_url'] for e in entries if e.get('page_url')})
        if entries:
            games, added = merge_master_list_into_games(games, entries)
            if added:
                log(f'  Added {added} new game(s) from the full library.')
                added_total += added
        else:
            log('  Could not fetch the full game library.')
    else:
        raise ValueError(f'unknown mode: {mode}')

    # Backfill page URLs for games that don't have one yet.
    for g in games:
        if not g.get('url') and g['title'] in all_page_urls:
            g['url'] = all_page_urls[g['title']]

    log('Fetching release years...')
    release_years = asyncio.run(fetch_release_years(games))
    for g in games:
        if g['title'] in release_years:
            g['release_year'] = release_years[g['title']]

    # Attach remote cover URLs (no local download) for games missing a cover.
    covers_found = 0
    for g in games:
        t = g['title']
        if not cover_map.get(t) and all_cover_urls.get(t):
            cover_map[t] = all_cover_urls[t]
        if cover_map.get(t):
            covers_found += 1

    games_out = internal_to_web(games, cover_map)
    games_ref.set({'games': games_out, 'updatedAt': firestore.SERVER_TIMESTAMP})
    log(f'Saved {len(games_out)} game(s) to Firestore.')
    status.done(added=added_total, covers_found=covers_found, total=len(games_out))


def main():
    uid = os.environ.get('SCRAPE_UID', '').strip()
    mode = os.environ.get('SCRAPE_MODE', '').strip()
    if not uid or not mode:
        print('SCRAPE_UID and SCRAPE_MODE are required', file=sys.stderr)
        sys.exit(2)

    client = get_client()
    status = Status(client.document(f'users/{uid}'), mode)
    try:
        run(client, uid, mode, status)
    except Exception as e:
        traceback.print_exc()
        try:
            status.fail(e)
        except Exception:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
