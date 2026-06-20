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

Requires the same dependencies as create_game_log_html.py:
  pip install playwright playwright-stealth
  python3 -m playwright install chromium
"""

import sys
import os
import asyncio

from create_game_log_html import (
    read_csv,
    write_csv,
    fetch_backloggd_list,
    fetch_release_years,
    fetch_all_covers,
    generate_html,
    compute_year_tabs,
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


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'gamelog.html'

    if not os.path.exists(csv_path):
        write_csv(csv_path, [])
        print(f"Created empty {csv_path}")

    print(f"Reading {csv_path}...")
    games = read_csv(csv_path)
    print(f"  Found {len(games)} game(s).")

    print(f"\nFetching full game library from {MASTER_GAMES_URL}...")
    master_entries = asyncio.run(fetch_backloggd_list(MASTER_GAMES_URL))

    master_cover_urls = {e['title']: e['cover_url'] for e in master_entries if e.get('cover_url')}
    master_page_urls = {e['title']: e['page_url'] for e in master_entries if e.get('page_url')}

    csv_changed = False
    if master_entries:
        games, added = merge_master_list_into_games(games, master_entries)
        if added:
            print(f"  Added {added} new game(s) from the full library.")
            csv_changed = True
    else:
        print("  ⚠  Could not fetch the full game library.")

    for game in games:
        if not game.get('url') and game['title'] in master_page_urls:
            game['url'] = master_page_urls[game['title']]
            csv_changed = True

    if csv_changed:
        write_csv(csv_path, games)
        print(f"\nCSV updated → {csv_path}")
    else:
        print(f"\nNo CSV changes from the full library scrape.")

    print(f"\nFetching release years...")
    release_years = asyncio.run(fetch_release_years(games))
    if release_years:
        for game in games:
            if game['title'] in release_years:
                game['release_year'] = release_years[game['title']]
        write_csv(csv_path, games)
        print(f"  CSV updated with release years → {csv_path}")

    print(f"\nFetching cover art...")
    covers = asyncio.run(fetch_all_covers(games, master_cover_urls))

    played_years = sorted(
        {int(g['year_played']) for g in games if g.get('year_played', '').strip().isdigit()},
        reverse=True,
    )

    years, year_modes = compute_year_tabs(games, played_years)
    print(f"\nYear tabs: {years[0] if years else 'none'} → {years[-1] if years else 'none'}")

    print(f"\nGenerating {out_path}...")
    html = generate_html(games, covers, page_urls=master_page_urls, years=years, year_modes=year_modes)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Done → {out_path}")


if __name__ == '__main__':
    main()
