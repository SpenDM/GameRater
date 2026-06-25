#!/usr/bin/env python3
"""
Game Ratings HTML Generator — Current Year edition
Usage: python3 create_game_log_current_year.py [input.csv] [output.html]
Defaults: games.csv -> gamelog.html

Like create_game_log_all_played_lists.py, but only scrapes the most
recent "Games Played YYYY" list from the Backloggd folder (e.g. if
"Games Played 2027", "2026", and "2025" all exist, only 2027 is
fetched). Older years already captured in the CSV are left alone and
still render in the generated HTML.

Requires the same dependencies as create_game_log_all_played_lists.py:
  pip install playwright playwright-stealth
  python3 -m playwright install chromium
"""

import sys
import os
import asyncio

from create_game_log_all_played_lists import (
    BACKLOGGD_FOLDER_URL,
    read_csv,
    write_csv,
    fetch_year_lists,
    fetch_backloggd_list,
    merge_list_into_games,
    fetch_release_years_and_update,
    fetch_covers_and_render,
)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def run_current_year(csv_path: str, out_path: str, folder_url: str = BACKLOGGD_FOLDER_URL,
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

    log("\nDiscovering year lists from Backloggd folder...")
    year_lists = asyncio.run(fetch_year_lists(folder_url))
    year_lists = year_lists[:1]
    if year_lists:
        log(f"  Using most recent year list: {year_lists[0][0]}")

    all_cover_urls: dict[str, str] = {}
    all_page_urls:  dict[str, str] = {}
    added_total = 0
    csv_changed = False
    current_year = None

    if year_lists:
        current_year, list_url = year_lists[0]

        log(f"\nFetching games for {current_year}...")
        entries = asyncio.run(fetch_backloggd_list(list_url))
        if not entries:
            log(f"  Could not fetch list for {current_year}.")
        else:
            games, added = merge_list_into_games(games, entries, year=current_year)
            if added:
                log(f"  Added {added} new game(s) for {current_year}.")
                added_total += added
                csv_changed = True
            all_cover_urls.update({e['title']: e['cover_url'] for e in entries if e.get('cover_url')})
            all_page_urls.update( {e['title']: e['page_url']  for e in entries if e.get('page_url')})

        # Backfill url for existing games that don't have one yet
        for game in games:
            if not game.get('url') and game['title'] in all_page_urls:
                game['url'] = all_page_urls[game['title']]
                csv_changed = True

        if csv_changed:
            write_csv(csv_path, games)
            log(f"\nCSV updated → {csv_path}")
        else:
            log("\nNo CSV changes.")

        log(f"  Page URLs captured: {len(all_page_urls)}")
    else:
        log("  ⚠  No year lists found — generating HTML from existing data only.")

    fetch_release_years_and_update(games, csv_path, log)

    # Derive played_years from the CSV's existing year_played values so that
    # years not touched by this run (only the latest year is scraped) still
    # show up correctly as tabs in the generated HTML.
    played_years = sorted(
        {int(g['year_played']) for g in games if g.get('year_played', '').strip().isdigit()},
        reverse=True,
    )

    result = fetch_covers_and_render(games, all_cover_urls, all_page_urls, played_years,
                                      out_path, covers_dir, log)

    log("")
    log("Tips:")
    log("  • Re-run any time to sync the current year's games from Backloggd and refresh the page.")
    log("  • Edit games.csv to add ratings and reviews for unrated games.")
    log("  • Drop manual covers in a covers/ folder as <slug>.jpg to override")
    log("    Backloggd lookups (e.g. 'hollow-knight.jpg').")

    return {'added': added_total, 'csv_changed': csv_changed, 'year': current_year, **result}


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'gamelog.html'
    run_current_year(csv_path, out_path, BACKLOGGD_FOLDER_URL)


if __name__ == '__main__':
    main()
