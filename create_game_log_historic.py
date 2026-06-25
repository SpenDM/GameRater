#!/usr/bin/env python3
"""
Game Ratings HTML Generator — Historic GOTY edition
Usage: python3 create_game_log_historic.py [input.csv] [output.html]
Defaults: games.csv -> gamelog.html

Adds every game from the user's full Backloggd library (not just the
"played by year" folder) into the CSV, then renders gamelog.html with
additional GOTY-only year tabs going back to the earliest release year
on record. Years 1999 and earlier show only the Game of the Year award
(no other award categories).

Requires the same dependencies as create_game_log_all_played_lists.py:
  pip install playwright playwright-stealth
  python3 -m playwright install chromium
"""

import sys
import os
import asyncio

from create_game_log_all_played_lists import (
    read_csv,
    write_csv,
    fetch_backloggd_list,
    fetch_release_years_and_update,
    fetch_covers_and_render,
)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MASTER_GAMES_URL = 'https://backloggd.com/u/smorrs/games/'


def merge_master_list_into_games(games: list[dict], list_entries: list[dict]) -> tuple[list[dict], int]:
    """Add any titles from the master games list not already in games. Returns (merged, added_count)."""
    existing = {g['title'].lower() for g in games}
    added = 0
    for entry in list_entries:
        if entry['title'].lower() not in existing:
            games.append({
                'title': entry['title'],
                'rating': 'unrated',
                'review': '',
                'url': entry.get('page_url') or '',
                'year_played': '',
                'release_year': '',
                'goty_categories': '',
            })
            existing.add(entry['title'].lower())
            added += 1
    return games, added


def run_historic(csv_path: str, out_path: str, master_url: str = MASTER_GAMES_URL,
                  covers_dir: str = "covers", progress_cb=None) -> dict:
    def log(msg: str) -> None:
        print(msg)
        if progress_cb:
            progress_cb(msg)

    if not os.path.exists(csv_path):
        write_csv(csv_path, [])
        log(f"Created empty {csv_path}")

    log(f"Reading {csv_path}...")
    games = read_csv(csv_path)
    log(f"  Found {len(games)} game(s).")

    log(f"\nFetching full game library from {master_url}...")
    master_entries = asyncio.run(fetch_backloggd_list(master_url))

    master_cover_urls = {e['title']: e['cover_url'] for e in master_entries if e.get('cover_url')}
    master_page_urls = {e['title']: e['page_url'] for e in master_entries if e.get('page_url')}

    csv_changed = False
    added_total = 0
    if master_entries:
        games, added = merge_master_list_into_games(games, master_entries)
        if added:
            log(f"  Added {added} new game(s) from the full library.")
            added_total += added
            csv_changed = True
    else:
        log("  ⚠  Could not fetch the full game library.")

    for game in games:
        if not game.get('url') and game['title'] in master_page_urls:
            game['url'] = master_page_urls[game['title']]
            csv_changed = True

    if csv_changed:
        write_csv(csv_path, games)
        log(f"\nCSV updated → {csv_path}")
    else:
        log("\nNo CSV changes from the full library scrape.")

    fetch_release_years_and_update(games, csv_path, log)

    played_years = sorted(
        {int(g['year_played']) for g in games if g.get('year_played', '').strip().isdigit()},
        reverse=True,
    )

    result = fetch_covers_and_render(games, master_cover_urls, master_page_urls, played_years,
                                      out_path, covers_dir, log)

    return {'added': added_total, 'csv_changed': csv_changed, **result}


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'gamelog.html'
    run_historic(csv_path, out_path, MASTER_GAMES_URL)


if __name__ == '__main__':
    main()
