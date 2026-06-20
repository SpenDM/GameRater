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
    fetch_release_years,
    fetch_all_covers,
    generate_html,
    compute_year_tabs,
)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'gamelog.html'

    if not os.path.exists(csv_path):
        write_csv(csv_path, [])
        print(f"Created empty {csv_path}")

    print(f"Reading {csv_path}...")
    games = read_csv(csv_path)
    print(f"  Found {len(games)} game(s).")

    print(f"\nDiscovering year lists from Backloggd folder...")
    year_lists = asyncio.run(fetch_year_lists(BACKLOGGD_FOLDER_URL))
    year_lists = year_lists[:1]
    if year_lists:
        print(f"  Using most recent year list: {year_lists[0][0]}")

    all_cover_urls: dict[str, str] = {}
    all_page_urls:  dict[str, str] = {}

    if year_lists:
        year, list_url = year_lists[0]
        csv_changed = False

        print(f"\nFetching games for {year}...")
        entries = asyncio.run(fetch_backloggd_list(list_url))
        if not entries:
            print(f"  Could not fetch list for {year}.")
        else:
            games, added = merge_list_into_games(games, entries, year=year)
            if added:
                print(f"  Added {added} new game(s) for {year}.")
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
            print(f"\nCSV updated → {csv_path}")
        else:
            print(f"\nNo CSV changes.")

        print(f"  Page URLs captured: {len(all_page_urls)}")
    else:
        print("  ⚠  No year lists found — generating HTML from existing data only.")

    print(f"\nFetching release years...")
    release_years = asyncio.run(fetch_release_years(games))
    if release_years:
        for game in games:
            if game['title'] in release_years:
                game['release_year'] = release_years[game['title']]
        write_csv(csv_path, games)
        print(f"  CSV updated with release years → {csv_path}")

    print(f"\nFetching cover art...")
    covers = asyncio.run(fetch_all_covers(games, all_cover_urls))

    # Derive played_years from the CSV's existing year_played values so that
    # years not touched by this run (only the latest year is scraped) still
    # show up correctly as tabs in the generated HTML.
    played_years = sorted(
        {int(g['year_played']) for g in games if g.get('year_played', '').strip().isdigit()},
        reverse=True,
    )

    years, year_modes = compute_year_tabs(games, played_years)

    print(f"\nGenerating {out_path}...")
    html = generate_html(games, covers, page_urls=all_page_urls, years=years, year_modes=year_modes)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Done → {out_path}")
    print()
    print("Tips:")
    print("  • Re-run any time to sync the current year's games from Backloggd and refresh the page.")
    print("  • Edit games.csv to add ratings and reviews for unrated games.")
    print("  • Drop manual covers in a covers/ folder as <slug>.jpg to override")
    print("    Backloggd lookups (e.g. 'hollow-knight.jpg').")


if __name__ == '__main__':
    main()
