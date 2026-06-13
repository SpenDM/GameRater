#!/usr/bin/env python3
"""
Game Ratings HTML Generator
Usage: python3 generate.py [input.csv] [output.html]
Defaults: games.csv -> index.html

Requires:
  pip install playwright playwright-stealth
  python3 -m playwright install chromium
Cover art is fetched from Backloggd at generation time and embedded in the HTML.
"""

import csv
import json
import sys
import os
import re
import asyncio
import time
from pathlib import Path

VALID_RATINGS = ['fantastic', 'great', 'good', 'okay', 'lame', 'awful', 'mixed']

RATING_LABELS = {
    'fantastic': 'Fantastic',
    'great':     'Great',
    'good':      'Good',
    'okay':      'Okay',
    'lame':      'Lame',
    'awful':     'Awful',
    'mixed':     'Mixed',
    'unrated':   'Unrated',
}

RATING_COLORS = {
    'fantastic': '#d4a017',
    'great':     '#7c3aed',
    'good':      '#2563eb',
    'okay':      '#c2620a',
    'lame':      '#7c5c3a',
    'awful':     '#16a34a',
    'mixed':     '#6b7280',
    'unrated':   '#3a3a4a',
}

BACKLOGGD_LIST_URL = 'https://backloggd.com/u/smorrs/list/games-played-2026/'


def read_csv(path: str) -> list[dict]:
    games = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            title = row.get('title', '').strip()
            rating = row.get('rating', '').strip().lower()
            review = row.get('review', '').strip()

            if not title:
                print(f"  Warning: row {i} has no title, skipping.")
                continue
            if rating not in VALID_RATINGS and rating != 'unrated':
                print(f"  Warning: '{rating}' is not a valid rating for '{title}'. "
                      f"Valid: {', '.join(VALID_RATINGS)}. Defaulting to 'unrated'.")
                rating = 'unrated'

            games.append({'title': title, 'rating': rating, 'review': review})
    return games


def write_csv(path: str, games: list[dict]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['title', 'rating', 'review'])
        writer.writeheader()
        writer.writerows(games)


async def fetch_backloggd_list(url: str) -> list[str]:
    """Scrape a Backloggd list page and return all game titles found."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        missing = 'playwright' if 'playwright' in str(e) else 'playwright-stealth'
        print(f"  ⚠  Missing package: {missing}")
        print(f"     Run: pip install playwright playwright-stealth && python3 -m playwright install chromium")
        return []

    titles = []
    print(f"  Fetching game list from {url}...")
    stealth = Stealth()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            }
        )

        try:
            page_num = 1
            while True:
                paged_url = url if page_num == 1 else f"{url.rstrip('/')}/?page={page_num}"
                page = await context.new_page()
                await stealth.apply_stealth_async(page)

                response = await page.goto(paged_url, wait_until="domcontentloaded", timeout=20000)
                status = response.status if response else 0

                if status >= 400:
                    print(f"    HTTP {status} — stopping.")
                    await page.close()
                    break

                # Wait for JS to render content
                await asyncio.sleep(2)

                # Scroll to bottom to trigger any lazy loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

                found_on_page = set()

                # IGDB cover image alt text — most reliable on Backloggd
                for selector in ['img[src*="igdb"][alt]', 'img[src*="images.igdb"][alt]']:
                    els = await page.query_selector_all(selector)
                    for el in els:
                        val = (await el.get_attribute('alt') or '').strip()
                        if val and len(val) > 1:
                            found_on_page.add(val)

                # Card/game title text elements
                for selector in ['.card-title a', '.game-title a', '.game-card .title',
                                  '.card-title', '.game-title', 'h3.title', 'h4.title']:
                    els = await page.query_selector_all(selector)
                    for el in els:
                        val = (await el.inner_text()).strip()
                        if val and len(val) > 1:
                            found_on_page.add(val)

                # Anchor title attributes on game links
                els = await page.query_selector_all('a[href*="/games/"][title]')
                for el in els:
                    val = (await el.get_attribute('title') or '').strip()
                    if val and len(val) > 1:
                        found_on_page.add(val)

                # Data attributes
                for attr in ['data-game-name', 'data-title']:
                    els = await page.query_selector_all(f'[{attr}]')
                    for el in els:
                        val = (await el.get_attribute(attr) or '').strip()
                        if val and len(val) > 1:
                            found_on_page.add(val)

                if not found_on_page:
                    print(f"    ⚠  Page {page_num}: no games found.")
                    print(f"    --- Page HTML (first 3000 chars) ---")
                    html = await page.content()
                    print(html[:3000])
                    print(f"    --- End HTML ---")
                    await page.close()
                    break

                new = [t for t in found_on_page if t.lower() not in {x.lower() for x in titles}]
                titles.extend(new)
                print(f"    Page {page_num}: found {len(found_on_page)} games ({len(new)} new)")

                # Check for next page
                next_btn = await page.query_selector(
                    'a[rel="next"], .pagination .next:not(.disabled), a.page-link[aria-label="Next"]'
                )
                await page.close()
                if not next_btn:
                    break
                page_num += 1

        except Exception as e:
            print(f"  ⚠  Error fetching list: {e}")

        await browser.close()

    print(f"  Total games found on list: {len(titles)}")
    return titles


def merge_list_into_games(games: list[dict], list_entries: list[dict]) -> tuple[list[dict], int]:
    """Add any titles from list_entries not already in games, as unrated. Returns (merged, added_count)."""
    existing = {g['title'].lower() for g in games}
    added = 0
    for entry in list_entries:
        if entry['title'].lower() not in existing:
            games.append({'title': entry['title'], 'rating': 'unrated', 'review': ''})
            existing.add(entry['title'].lower())
            added += 1
    return games, added


def _make_stealth_launch_args():
    return dict(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--no-sandbox',
            '--disable-dev-shm-usage',
        ]
    )


def _make_stealth_context_args():
    return dict(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1440, "height": 900},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }
    )


async def _stealth_page(context, stealth):
    page = await context.new_page()
    await stealth.apply_stealth_async(page)
    return page


async def fetch_backloggd_list(url: str) -> list[dict]:
    """Scrape a Backloggd list page. Returns list of {title, cover_url} dicts."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        missing = 'playwright-stealth' if 'stealth' in str(e) else 'playwright'
        print(f"  ⚠  Missing package: {missing}")
        print(f"     Run: pip install playwright playwright-stealth && python3 -m playwright install chromium")
        return []

    entries = []
    print(f"  Fetching game list from {url}...")
    stealth = Stealth()

    async with async_playwright() as p:
        browser = await p.chromium.launch(**_make_stealth_launch_args())
        context = await browser.new_context(**_make_stealth_context_args())

        try:
            page_num = 1
            while True:
                paged_url = url if page_num == 1 else f"{url.rstrip('/')}/?page={page_num}"
                page = await _stealth_page(context, stealth)

                response = await page.goto(paged_url, wait_until="domcontentloaded", timeout=20000)
                status = response.status if response else 0

                if status >= 400:
                    print(f"    HTTP {status} — stopping.")
                    await page.close()
                    break

                await asyncio.sleep(2)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

                found_on_page = {}  # title -> cover_url

                # Grab cover images from IGDB CDN — src=cover URL, alt=game title
                for selector in ['img[src*="igdb"][alt]', 'img[src*="images.igdb"][alt]']:
                    els = await page.query_selector_all(selector)
                    for el in els:
                        title = (await el.get_attribute('alt') or '').strip()
                        cover = (await el.get_attribute('src') or '').strip()
                        if title and len(title) > 1:
                            found_on_page[title] = cover or None

                # Fallback: card title text (no cover)
                if not found_on_page:
                    for selector in ['.card-title a', '.game-title a', '.card-title', '.game-title', 'h3.title']:
                        els = await page.query_selector_all(selector)
                        for el in els:
                            val = (await el.inner_text()).strip()
                            if val and len(val) > 1:
                                found_on_page.setdefault(val, None)

                    for attr in ['data-game-name', 'data-title']:
                        els = await page.query_selector_all(f'[{attr}]')
                        for el in els:
                            val = (await el.get_attribute(attr) or '').strip()
                            if val and len(val) > 1:
                                found_on_page.setdefault(val, None)

                if not found_on_page:
                    print(f"    ⚠  Page {page_num}: no games found.")
                    html = await page.content()
                    print(f"    --- Page HTML (first 3000 chars) ---\n{html[:3000]}\n    ---")
                    await page.close()
                    break

                existing_titles = {e['title'].lower() for e in entries}
                new = [(t, c) for t, c in found_on_page.items() if t.lower() not in existing_titles]
                for title, cover in new:
                    entries.append({'title': title, 'cover_url': cover})
                print(f"    Page {page_num}: found {len(found_on_page)} games ({len(new)} new)")

                next_btn = await page.query_selector(
                    'a[rel="next"], .pagination .next:not(.disabled), a.page-link[aria-label="Next"]'
                )
                await page.close()
                if not next_btn:
                    break
                page_num += 1

        except Exception as e:
            print(f"  ⚠  Error fetching list: {e}")

        await browser.close()

    print(f"  Total games found on list: {len(entries)}")
    return entries


def title_to_backloggd_slug(title: str) -> str:
    """Convert a game title to a Backloggd URL slug."""
    import unicodedata
    # Normalise accented chars → ascii equivalents
    slug = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('ascii')
    slug = slug.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)
    return slug


async def fetch_all_covers(games: list[dict], list_cover_urls: dict[str, str] | None = None) -> dict[str, str | None]:
    """Download and cache cover art for all games.
    Cover URLs come from the list page scrape (list_cover_urls).
    Games already in covers/ are skipped. Anything without a URL gets a placeholder.
    """
    import urllib.request

    covers = {}
    Path("covers").mkdir(exist_ok=True)
    list_cover_urls = list_cover_urls or {}

    print(f"  Processing cover art for {len(games)} games...")

    for game in games:
        title = game['title']
        local_slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

        # 1. Already cached locally?
        for ext in ['jpg', 'jpeg', 'png', 'webp']:
            local_path = Path(f"covers/{local_slug}.{ext}")
            if local_path.exists():
                covers[title] = str(local_path)
                print(f"  ✓ {title}: cached")
                break

        if title in covers:
            continue

        # 2. Download from URL grabbed off the list page
        cover_url = list_cover_urls.get(title)
        if not cover_url:
            covers[title] = None
            print(f"  ✗ {title}: no cover URL")
            continue

        print(f"  → {title}", end='', flush=True)
        url_path = cover_url.split('?')[0]
        ext = url_path.rsplit('.', 1)[-1].lower()
        if ext not in ('jpg', 'jpeg', 'png', 'webp'):
            ext = 'jpg'
        local_path = Path(f"covers/{local_slug}.{ext}")
        try:
            req = urllib.request.Request(cover_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                local_path.write_bytes(resp.read())
            covers[title] = str(local_path)
            print(f" ✓ (saved)")
        except Exception as e:
            covers[title] = cover_url  # fall back to remote URL
            print(f" ✓ (url only: {e})")

    found = sum(1 for v in covers.values() if v)
    print(f"  Covers found: {found}/{len(games)}")
    return covers


def generate_html(games: list[dict], covers: dict[str, str | None],
                  title: str = "Game Log") -> str:

    # Attach cover URLs to game data
    games_with_covers = []
    for g in games:
        entry = dict(g)
        entry['cover'] = covers.get(g['title']) or ''
        games_with_covers.append(entry)

    games_json = json.dumps(games_with_covers, ensure_ascii=False)

    rating_css_vars = '\n'.join(
        f'    --color-{r}: {c};' for r, c in RATING_COLORS.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg:          #0f0f13;
      --surface:     #18181f;
      --surface2:    #1f1f2a;
      --border:      #2a2a38;
      --text:        #e8e8f0;
      --text-dim:    #7a7a99;
      --text-muted:  #4a4a66;
      --accent:      #a78bfa;
{rating_css_vars}
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', sans-serif;
      font-size: 15px;
      line-height: 1.6;
      min-height: 100vh;
    }}

    /* ── Header ── */
    header {{
      border-bottom: 1px solid var(--border);
      padding: 2.5rem 2rem 2rem;
      max-width: 1100px;
      margin: 0 auto;
    }}

    header h1 {{
      font-family: 'Syne', sans-serif;
      font-size: clamp(1.8rem, 4vw, 2.8rem);
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text);
    }}

    header h1 span {{ color: var(--accent); }}

    .header-meta {{
      margin-top: 0.5rem;
      color: var(--text-dim);
      font-size: 0.9rem;
    }}

    /* ── Toolbar (filter bar + view toggle) ── */
    .toolbar {{
      max-width: 1100px;
      margin: 1.5rem auto 0;
      padding: 0 2rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }}

    /* ── Filter bar ── */
    .filter-bar {{
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
      align-items: center;
      flex: 1;
    }}

    .filter-label {{
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      margin-right: 0.25rem;
    }}

    .filter-btn {{
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text-dim);
      padding: 0.3rem 0.8rem;
      border-radius: 99px;
      font-size: 0.8rem;
      font-family: 'Inter', sans-serif;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s ease;
    }}

    .filter-btn:hover {{ border-color: var(--accent); color: var(--text); }}

    .filter-btn.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #0f0f13;
      font-weight: 600;
    }}

    /* ── View toggle ── */
    .view-toggle {{
      display: flex;
      gap: 2px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 3px;
      flex-shrink: 0;
    }}

    .view-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      width: 30px;
      height: 28px;
      border-radius: 5px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
    }}

    .view-btn:hover {{ color: var(--text); background: var(--surface2); }}

    .view-btn.active {{
      background: var(--accent);
      color: #0f0f13;
    }}

    /* ── Game list ── */
    main {{
      max-width: 1100px;
      margin: 2rem auto 4rem;
      padding: 0 2rem;
    }}

    .game-count {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-bottom: 1.25rem;
    }}

    .game-list {{
      display: flex;
      flex-direction: column;
      gap: 1px;
      background: var(--border);
      border-radius: 12px;
      overflow: hidden;
    }}

    /* ── Game row ── */
    .game-row {{
      display: grid;
      grid-template-columns: 60px 1fr auto;
      background: var(--surface);
      transition: background 0.15s ease;
      position: relative;
    }}

    .game-row:hover {{ background: var(--surface2); }}

    .game-row::before {{
      content: '';
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 3px;
      background: var(--row-accent);
      opacity: 0.7;
    }}

    /* ── Cover ── */
    .game-cover-wrap {{
      width: 60px;
      min-height: 80px;
      flex-shrink: 0;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--surface2);
    }}

    .game-cover {{
      width: 60px;
      height: 80px;
      object-fit: cover;
      display: block;
    }}

    .cover-placeholder {{
      width: 60px;
      height: 80px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: 'Syne', sans-serif;
      font-size: 1.4rem;
      font-weight: 800;
      color: var(--text-muted);
    }}

    /* ── Body ── */
    .game-body {{
      padding: 1rem 1.25rem;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 0.35rem;
      min-width: 0;
    }}

    .game-title {{
      font-family: 'Syne', sans-serif;
      font-size: 1rem;
      font-weight: 700;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .game-review {{
      font-size: 0.84rem;
      color: var(--text-dim);
      line-height: 1.5;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    /* ── Rating column ── */
    .game-rating-col {{
      padding: 1rem 1.25rem 1rem 0.75rem;
      display: flex;
      align-items: center;
      flex-shrink: 0;
    }}

    .rating-pill {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      padding: 0.25rem 0.65rem;
      border-radius: 99px;
      background: color-mix(in srgb, var(--row-accent) 15%, transparent);
      color: var(--row-accent);
      border: 1px solid color-mix(in srgb, var(--row-accent) 30%, transparent);
      white-space: nowrap;
    }}

    /* ── Empty state ── */
    .empty {{
      text-align: center;
      padding: 4rem 2rem;
      color: var(--text-muted);
      font-size: 0.9rem;
    }}

    /* ── Tier view ── */
    .tier-view {{
      display: flex;
      flex-direction: column;
      gap: 1px;
      background: var(--border);
      border-radius: 12px;
      overflow: hidden;
    }}

    .tier-row {{
      display: flex;
      align-items: stretch;
      background: var(--surface);
      min-height: 150px;
      position: relative;
    }}

    .tier-row:hover {{ background: var(--surface2); }}

    /* left accent stripe */
    .tier-row::before {{
      content: '';
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 3px;
      background: var(--tier-color);
      opacity: 0.7;
    }}

    .tier-label-col {{
      width: 140px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      border-right: 1px solid var(--border);
    }}

    .tier-rating-img {{
      width: 140px;
      height: 140px;
      object-fit: contain;
      display: block;
    }}

    /* fallback pill if image missing */
    .tier-rating-pill {{
      font-family: 'Syne', sans-serif;
      font-size: 0.8rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--tier-color);
      text-align: center;
      white-space: nowrap;
    }}

    .tier-covers {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 14px 16px;
      align-items: flex-start;
      align-content: flex-start;
      flex: 1;
    }}

    .tier-cover-item {{
      position: relative;
      width: 88px;
      flex-shrink: 0;
      cursor: default;
    }}

    .tier-cover-item img,
    .tier-cover-placeholder {{
      width: 88px;
      height: 117px;
      object-fit: cover;
      display: block;
      border-radius: 4px;
      border: 1px solid var(--border);
    }}

    .tier-cover-placeholder {{
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--surface2);
      font-family: 'Syne', sans-serif;
      font-size: 1.3rem;
      font-weight: 800;
      color: var(--text-muted);
      border-radius: 4px;
      border: 1px solid var(--border);
    }}

    /* tooltip on hover */
    .tier-cover-item .cover-tooltip {{
      display: none;
      position: absolute;
      bottom: calc(100% + 6px);
      left: 50%;
      transform: translateX(-50%);
      background: #0f0f13;
      color: var(--text);
      font-size: 0.72rem;
      font-weight: 600;
      padding: 0.3rem 0.6rem;
      border-radius: 5px;
      border: 1px solid var(--border);
      white-space: nowrap;
      z-index: 10;
      pointer-events: none;
      max-width: 160px;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .tier-cover-item:hover .cover-tooltip {{ display: block; }}

    .tier-empty {{
      padding: 1rem;
      color: var(--text-muted);
      font-size: 0.82rem;
      font-style: italic;
      align-self: center;
    }}

    /* ── Responsive ── */
    @media (max-width: 600px) {{
      header, .toolbar, main {{ padding-left: 1rem; padding-right: 1rem; }}
      .game-body {{ padding: 0.75rem 0.9rem; }}
      .tier-label-col {{ width: 110px; }}
      .tier-rating-img {{ width: 64px; height: 64px; }}
      .tier-cover-item {{ width: 66px; }}
      .tier-cover-item img, .tier-cover-placeholder {{ width: 66px; height: 88px; }}
    }}
  </style>
</head>
<body>

<header>
  <h1>Game <span>Log</span></h1>
  <p class="header-meta" id="header-meta"></p>
</header>

<div class="toolbar">
  <div class="filter-bar" id="filter-bar">
    <span class="filter-label">Filter</span>
    <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
    <button class="filter-btn" onclick="setFilter('fantastic', this)">Fantastic</button>
    <button class="filter-btn" onclick="setFilter('great', this)">Great</button>
    <button class="filter-btn" onclick="setFilter('good', this)">Good</button>
    <button class="filter-btn" onclick="setFilter('okay', this)">Okay</button>
    <button class="filter-btn" onclick="setFilter('mixed', this)">Mixed</button>
    <button class="filter-btn" onclick="setFilter('lame', this)">Lame</button>
    <button class="filter-btn" onclick="setFilter('awful', this)">Awful</button>
    <button class="filter-btn" onclick="setFilter('unrated', this)">Unrated</button>
  </div>
  <div class="view-toggle">
    <button class="view-btn" id="btn-list" onclick="setView('list')" title="List view">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="5" y="2" width="9" height="2" rx="1" fill="currentColor"/><rect x="5" y="7" width="9" height="2" rx="1" fill="currentColor"/><rect x="5" y="12" width="9" height="2" rx="1" fill="currentColor"/><rect x="2" y="2" width="2" height="2" rx="0.5" fill="currentColor"/><rect x="2" y="7" width="2" height="2" rx="0.5" fill="currentColor"/><rect x="2" y="12" width="2" height="2" rx="0.5" fill="currentColor"/></svg>
    </button>
    <button class="view-btn active" id="btn-tier" onclick="setView('tier')" title="Tier view">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="2" width="14" height="3.5" rx="1" fill="currentColor" opacity="0.9"/><rect x="1" y="6.5" width="14" height="3" rx="1" fill="currentColor" opacity="0.65"/><rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity="0.4"/></svg>
    </button>
  </div>
</div>

<main>
  <p class="game-count" id="game-count"></p>
  <div class="game-list" id="game-list" style="display:none;"></div>
  <div class="tier-view" id="tier-view"></div>
</main>

<script>
const GAMES = {games_json};

const RATING_COLORS = {{
  fantastic: '#d4a017',
  great:     '#7c3aed',
  good:      '#2563eb',
  okay:      '#c2620a',
  lame:      '#7c5c3a',
  awful:     '#16a34a',
  mixed:     '#6b7280',
  unrated:   '#3a3a4a',
}};

const RATING_LABELS = {{
  fantastic: 'Fantastic',
  great:     'Great',
  good:      'Good',
  okay:      'Okay',
  lame:      'Lame',
  awful:     'Awful',
  mixed:     'Mixed',
  unrated:   'Unrated',
}};

const ORDER = ['fantastic','great','good','okay','mixed','lame','awful'];

function escapeHtml(str) {{
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function getInitial(title) {{
  return title.trim()[0]?.toUpperCase() ?? '?';
}}

// ── List view ────────────────────────────────────────

function buildRow(game) {{
  const color = RATING_COLORS[game.rating] || '#888';
  const label = RATING_LABELS[game.rating] || game.rating;

  const coverHtml = game.cover
    ? `<img class="game-cover" src="${{escapeHtml(game.cover)}}" alt="${{escapeHtml(game.title)}}"
           onerror="this.outerHTML='<div class=\\'cover-placeholder\\'>${{getInitial(game.title)}}</div>'" />`
    : `<div class="cover-placeholder">${{getInitial(game.title)}}</div>`;

  const reviewHtml = game.review
    ? `<p class="game-review">${{escapeHtml(game.review)}}</p>`
    : '';

  const row = document.createElement('div');
  row.className = 'game-row';
  row.dataset.rating = game.rating;
  row.style.setProperty('--row-accent', color);
  row.innerHTML = `
    <div class="game-cover-wrap">${{coverHtml}}</div>
    <div class="game-body">
      <div class="game-title">${{escapeHtml(game.title)}}</div>
      ${{reviewHtml}}
    </div>
    <div class="game-rating-col">
      <span class="rating-pill">${{label}}</span>
    </div>
  `;
  return row;
}}

// ── Tier view ─────────────────────────────────────────

function buildTierRow(rating, games) {{
  const color = RATING_COLORS[rating] || '#888';
  const label = RATING_LABELS[rating] || rating;

  const row = document.createElement('div');
  row.className = 'tier-row';
  row.style.setProperty('--tier-color', color);

  // Label column
  const labelCol = document.createElement('div');
  labelCol.className = 'tier-label-col';

  if (rating === 'unrated') {{
    // Unrated has no image — use a styled text label
    const span = document.createElement('span');
    span.className = 'tier-rating-pill';
    span.textContent = label;
    labelCol.appendChild(span);
  }} else {{
    // Rated tiers: rating image with text pill fallback
    const img = document.createElement('img');
    img.className = 'tier-rating-img';
    img.src = `images/${{rating}}.png`;
    img.alt = label;
    img.onerror = function() {{
      this.outerHTML = `<span class="tier-rating-pill">${{label}}</span>`;
    }};
    labelCol.appendChild(img);
  }}

  row.appendChild(labelCol);

  // Covers area
  const coversDiv = document.createElement('div');
  coversDiv.className = 'tier-covers';

  if (games.length === 0) {{
    const empty = document.createElement('span');
    empty.className = 'tier-empty';
    empty.textContent = 'No games yet';
    coversDiv.appendChild(empty);
  }} else {{
    games.forEach(game => {{
      const item = document.createElement('div');
      item.className = 'tier-cover-item';

      const tooltip = document.createElement('span');
      tooltip.className = 'cover-tooltip';
      tooltip.textContent = game.title;

      const coverEl = game.cover
        ? (() => {{
            const i = document.createElement('img');
            i.src = game.cover;
            i.alt = game.title;
            i.onerror = function() {{
              this.outerHTML = `<div class="tier-cover-placeholder">${{getInitial(game.title)}}</div>`;
            }};
            return i;
          }})()
        : (() => {{
            const d = document.createElement('div');
            d.className = 'tier-cover-placeholder';
            d.textContent = getInitial(game.title);
            return d;
          }})();

      item.appendChild(tooltip);
      item.appendChild(coverEl);
      coversDiv.appendChild(item);
    }});
  }}

  row.appendChild(coversDiv);
  return row;
}}

// ── View & filter state ───────────────────────────────

let currentFilter = 'all';
let currentView = 'list';

function setView(view) {{
  currentView = view;
  document.getElementById('btn-list').classList.toggle('active', view === 'list');
  document.getElementById('btn-tier').classList.toggle('active', view === 'tier');

  // Hide filter bar in tier mode (all tiers always shown)
  document.getElementById('filter-bar').style.display = view === 'tier' ? 'none' : '';

  if (view === 'list') {{
    document.getElementById('game-list').style.display = '';
    document.getElementById('tier-view').style.display = 'none';
    document.getElementById('game-count').style.display = '';
    renderList();
  }} else {{
    document.getElementById('game-list').style.display = 'none';
    document.getElementById('tier-view').style.display = '';
    document.getElementById('game-count').style.display = 'none';
    renderTiers();
  }}
}}

function setFilter(filter, btn) {{
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderList();
}}

function renderList() {{
  const list = document.getElementById('game-list');
  const countEl = document.getElementById('game-count');
  list.innerHTML = '';

  const filtered = currentFilter === 'all'
    ? GAMES
    : GAMES.filter(g => g.rating === currentFilter);

  if (filtered.length === 0) {{
    list.innerHTML = '<div class="empty">No games with this rating yet.</div>';
    countEl.textContent = '';
    return;
  }}

  const sorted = [...filtered].sort((a, b) => ORDER.indexOf(a.rating) - ORDER.indexOf(b.rating));
  countEl.textContent = `${{sorted.length}} game${{sorted.length !== 1 ? 's' : ''}}`;
  sorted.forEach(game => list.appendChild(buildRow(game)));
}}

function renderTiers() {{
  const container = document.getElementById('tier-view');
  container.innerHTML = '';

  ORDER.forEach(rating => {{
    const games = GAMES.filter(g => g.rating === rating);
    container.appendChild(buildTierRow(rating, games));
  }});

  // Unrated section at the bottom
  const unratedGames = GAMES.filter(g => g.rating === 'unrated');
  if (unratedGames.length > 0) {{
    const divider = document.createElement('div');
    divider.style.cssText = 'height:1px; background:var(--border); margin:8px 0;';
    container.appendChild(divider);
    container.appendChild(buildTierRow('unrated', unratedGames));
  }}
}}

(function init() {{
  document.getElementById('header-meta').textContent =
    `${{GAMES.length}} game${{GAMES.length !== 1 ? 's' : ''}} rated`;
  setView('tier');
}})();
</script>
</body>
</html>
"""


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'index.html'

    if not os.path.exists(csv_path):
        # Create empty CSV if it doesn't exist yet
        write_csv(csv_path, [])
        print(f"Created empty {csv_path}")

    print(f"Reading {csv_path}...")
    games = read_csv(csv_path)
    print(f"  Found {len(games)} game(s).")

    print(f"\nFetching game list from Backloggd...")
    list_entries = asyncio.run(fetch_backloggd_list(BACKLOGGD_LIST_URL))

    list_cover_urls = {}
    if list_entries:
        games, added = merge_list_into_games(games, list_entries)
        if added > 0:
            print(f"  Added {added} new unrated game(s) to {csv_path}.")
            write_csv(csv_path, games)
        else:
            print(f"  No new games to add.")
        list_cover_urls = {e['title']: e['cover_url'] for e in list_entries if e.get('cover_url')}
        print(f"  Cover URLs grabbed from list page: {len(list_cover_urls)}")
    else:
        print(f"  Could not fetch list or list was empty.")

    print(f"\nFetching cover art...")
    covers = asyncio.run(fetch_all_covers(games, list_cover_urls))

    print(f"\nGenerating {out_path}...")
    html = generate_html(games, covers)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Done → {out_path}")
    print()
    print("Tips:")
    print("  • Re-run any time to sync new games from Backloggd and refresh the page.")
    print("  • Edit games.csv to add ratings and reviews for unrated games.")
    print("  • Drop manual covers in a covers/ folder as <slug>.jpg to override")
    print("    Backloggd lookups (e.g. 'hollow-knight.jpg').")


if __name__ == '__main__':
    main()