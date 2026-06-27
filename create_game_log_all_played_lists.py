#!/usr/bin/env python3
"""
Game Ratings HTML Generator
Usage: python3 create_game_log_all_played_lists.py [input.csv] [output.html]
Defaults: games.csv -> gamelog.html

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
from pathlib import Path

# Ensure Unicode output works on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VALID_RATINGS = ['fantastic', 'great', 'good', 'okay', 'lame', 'mixed']

RATING_LABELS = {
    'fantastic': 'Fantastic',
    'great':     'Great',
    'good':      'Good',
    'okay':      'Okay',
    'lame':      'Lame',
    'mixed':     'Mixed',
    'unrated':   'Unrated',
}

RATING_COLORS = {
    'fantastic': '#d4a017',
    'great':     '#7c3aed',
    'good':      '#2563eb',
    'okay':      '#c2620a',
    'lame':      '#7c5c3a',
    'mixed':     '#6b7280',
    'unrated':   '#3a3a4a',
}

BACKLOGGD_FOLDER_URL = 'https://backloggd.com/u/smorrs/lists/folder/games-played-by-year/'

GOTY_CATEGORIES = [
    {'key': 'goty',            'label': 'Game of the Year'},
    {'key': 'puzzle_strategy', 'label': 'Puzzle/Strategy'},
    {'key': 'action',          'label': 'Action'},
    {'key': 'pickup_n_play',   'label': "Pick Up 'n Play"},
    {'key': 'novelty',         'label': 'Novelty'},
    {'key': 'narrative',       'label': 'Narrative'},
    {'key': 'world',           'label': 'World'},
    {'key': 'visuals',         'label': 'Visuals'},
    {'key': 'audio',           'label': 'Audio'},
]


# ── CSV I/O ───────────────────────────────────────────────────────────────────

def read_csv(path: str) -> list[dict]:
    games = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            title = row.get('title', '').strip()
            rating = row.get('rating', '').strip().lower()
            review = row.get('review', '').strip()
            url = row.get('url', '').strip()
            year_played = row.get('year_played', '').strip()
            release_year = row.get('release_year', '').strip()
            goty_categories = row.get('goty_categories', '').strip()

            if not title:
                print(f"  Warning: row {i} has no title, skipping.")
                continue
            if rating not in VALID_RATINGS and rating != 'unrated':
                print(f"  Warning: '{rating}' is not a valid rating for '{title}'. "
                      f"Valid: {', '.join(VALID_RATINGS)}. Defaulting to 'unrated'.")
                rating = 'unrated'

            games.append({'title': title, 'rating': rating, 'review': review,
                          'url': url, 'year_played': year_played,
                          'release_year': release_year, 'goty_categories': goty_categories})
    return games


def write_csv(path: str, games: list[dict]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=['title', 'rating', 'review', 'url', 'year_played',
                           'release_year', 'goty_categories'],
            extrasaction='ignore',
        )
        writer.writeheader()
        writer.writerows(games)


# ── Playwright helpers ────────────────────────────────────────────────────────

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


# ── Backloggd scraping ────────────────────────────────────────────────────────

async def fetch_year_lists(folder_url: str) -> list[tuple[int, str]]:
    """Scrape the Backloggd folder page. Returns [(year, list_url), ...] sorted descending."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        missing = 'playwright-stealth' if 'stealth' in str(e) else 'playwright'
        print(f"  ⚠  Missing package: {missing}")
        print(f"     Run: pip install playwright playwright-stealth && python3 -m playwright install chromium")
        return []

    results: list[tuple[int, str]] = []
    print(f"  Fetching year lists from {folder_url}...")
    stealth = Stealth()

    async with async_playwright() as p:
        browser = await p.chromium.launch(**_make_stealth_launch_args())
        context = await browser.new_context(**_make_stealth_context_args())
        try:
            page = await _stealth_page(context, stealth)
            response = await page.goto(folder_url, wait_until="domcontentloaded", timeout=20000)
            if response and response.status >= 400:
                print(f"    HTTP {response.status} — giving up.")
                await page.close()
                await browser.close()
                return []
            await asyncio.sleep(2)

            links = await page.evaluate('''() => {
                const out = [];
                document.querySelectorAll('a[href*="/list/"]').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || a.textContent || '').trim();
                    out.push({ href, text });
                });
                return out;
            }''')

            seen: set[int] = set()
            for link in links:
                href = link['href']
                text = link['text']
                m = re.search(r'\b(20\d{2})\b', text) or re.search(r'\b(20\d{2})\b', href)
                if not m:
                    continue
                year = int(m.group(1))
                if year in seen:
                    continue
                seen.add(year)
                if href.startswith('/'):
                    full_url = f"https://backloggd.com{href}"
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                results.append((year, full_url))
                print(f"    Found: {year} → {full_url}")

            await page.close()
        except Exception as e:
            print(f"  ⚠  Error fetching folder page: {e}")
        await browser.close()

    results.sort(key=lambda t: t[0], reverse=True)
    print(f"  Found {len(results)} year list(s).")
    return results


async def fetch_backloggd_list(url: str) -> list[dict]:
    """Scrape a Backloggd list page. Returns list of {title, cover_url, page_url} dicts."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        missing = 'playwright-stealth' if 'stealth' in str(e) else 'playwright'
        print(f"  ⚠  Missing package: {missing}")
        print(f"     Run: pip install playwright playwright-stealth && python3 -m playwright install chromium")
        return []

    entries: list[dict] = []
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

                # Wait for IGDB cover images to appear (handles JS-rendered content)
                try:
                    await page.wait_for_selector('img[src*="igdb"][alt]', timeout=8000)
                except Exception:
                    pass

                # Single JS call: find IGDB cover imgs (title=alt), then walk DOM
                # to find the associated /games/ link (may be ancestor OR sibling).
                raw = await page.evaluate('''() => {
                    const seen = new Set(), results = [];
                    document.querySelectorAll('img[alt]').forEach(img => {
                        const src = img.src || img.getAttribute('data-src') || '';
                        if (!src.includes('igdb')) return;
                        const title = img.alt.trim();
                        if (!title || title.length <= 1 || seen.has(title)) return;
                        // Walk up ancestors; at each level also scan descendants for a /games/ link
                        let href = null;
                        let el = img;
                        for (let i = 0; i < 8 && el; i++) {
                            if (el.tagName === 'A') {
                                const h = el.getAttribute('href') || '';
                                if (h.includes('/games/')) { href = h; break; }
                            }
                            if (el.parentElement) {
                                const a = el.parentElement.querySelector('a[href*="/games/"]');
                                if (a) { href = a.getAttribute('href'); break; }
                            }
                            el = el.parentElement;
                        }
                        seen.add(title);
                        results.push({ title, cover: src || null, href: href || null });
                    });
                    return results;
                }''')

                found_on_page: dict[str, dict] = {}
                for item in raw:
                    title = item['title']
                    cover = item.get('cover') or None
                    href = item.get('href') or ''
                    page_url = (f"https://www.backloggd.com{href}" if href.startswith('/') else href) or None
                    found_on_page[title] = {'cover_url': cover, 'page_url': page_url}

                # Fallback: card title text (no cover or url)
                if not found_on_page:
                    for selector in ['.card-title a', '.game-title a', '.card-title', '.game-title', 'h3.title']:
                        els = await page.query_selector_all(selector)
                        for el in els:
                            val = (await el.inner_text()).strip()
                            if val and len(val) > 1:
                                found_on_page.setdefault(val, {'cover_url': None, 'page_url': None})
                    for attr in ['data-game-name', 'data-title']:
                        els = await page.query_selector_all(f'[{attr}]')
                        for el in els:
                            val = (await el.get_attribute(attr) or '').strip()
                            if val and len(val) > 1:
                                found_on_page.setdefault(val, {'cover_url': None, 'page_url': None})

                if not found_on_page:
                    print(f"    ⚠  Page {page_num}: no games found — stopping.")
                    if page_num == 1:
                        html = await page.content()
                        print(f"    --- Page HTML (first 3000 chars) ---\n{html[:3000]}\n    ---")
                    await page.close()
                    break

                existing_titles = {e['title'].lower() for e in entries}
                new = [(t, d) for t, d in found_on_page.items() if t.lower() not in existing_titles]
                for title, data in new:
                    entries.append({
                        'title': title,
                        'cover_url': data['cover_url'],
                        'page_url': data['page_url'],
                    })
                print(f"    Page {page_num}: found {len(found_on_page)} games ({len(new)} new)")
                await page.close()

                if not new:
                    # Every title on this page was already seen — either we've run
                    # past the last page (site re-serves the final page) or hit a
                    # genuine duplicate-only page. Either way, stop.
                    break
                if page_num > 100:
                    print("    ⚠  Hit 100-page safety cap — stopping.")
                    break
                page_num += 1

        except Exception as e:
            print(f"  ⚠  Error fetching list: {e}")

        await browser.close()

    print(f"  Total games found on list: {len(entries)}")
    return entries


async def fetch_all_covers(games: list[dict], list_cover_urls: dict[str, str] | None = None,
                            covers_dir: str = "covers") -> dict[str, str | None]:
    """Download and cache cover art for all games."""
    import urllib.request

    covers: dict[str, str | None] = {}
    Path(covers_dir).mkdir(parents=True, exist_ok=True)
    list_cover_urls = list_cover_urls or {}

    print(f"  Processing cover art for {len(games)} games...")

    for game in games:
        title = game['title']
        local_slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

        for ext in ['jpg', 'jpeg', 'png', 'webp']:
            local_path = Path(covers_dir) / f"{local_slug}.{ext}"
            if local_path.exists():
                covers[title] = str(local_path)
                print(f"  ✓ {title}: cached")
                break

        if title in covers:
            continue

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
        local_path = Path(covers_dir) / f"{local_slug}.{ext}"
        try:
            req = urllib.request.Request(cover_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                local_path.write_bytes(resp.read())
            covers[title] = str(local_path)
            print(f" ✓ (saved)")
        except Exception as e:
            covers[title] = cover_url
            print(f" ✓ (url only: {e})")

    found = sum(1 for v in covers.values() if v)
    print(f"  Covers found: {found}/{len(games)}")
    return covers


async def fetch_release_years(games: list[dict]) -> dict[str, str]:
    """Visit each game's Backloggd page and scrape its release year."""
    to_fetch = [g for g in games if g.get('url') and not g.get('release_year')]
    years: dict[str, str] = {}
    if not to_fetch:
        return years

    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        missing = 'playwright-stealth' if 'stealth' in str(e) else 'playwright'
        print(f"  ⚠  Missing package: {missing}")
        print(f"     Run: pip install playwright playwright-stealth && python3 -m playwright install chromium")
        return years

    print(f"  Fetching release years for {len(to_fetch)} game(s)...")
    stealth = Stealth()

    async with async_playwright() as p:
        browser = await p.chromium.launch(**_make_stealth_launch_args())
        context = await browser.new_context(**_make_stealth_context_args())

        for game in to_fetch:
            title = game['title']
            url = game['url']
            print(f"  → {title}", end='', flush=True)
            page = await _stealth_page(context, stealth)
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                if response and response.status >= 400:
                    print(f" ✗ (HTTP {response.status})")
                    await page.close()
                    continue
                html = await page.evaluate("() => document.documentElement.outerHTML")
                m = re.search(r'release_year:(\d{4})', html)
                if m:
                    years[title] = m.group(1)
                    print(f" ✓ ({m.group(1)})")
                else:
                    print(" ✗ (not found)")
            except Exception as e:
                print(f" ✗ ({e})")
            await page.close()

        await browser.close()

    print(f"  Release years found: {len(years)}/{len(to_fetch)}")
    return years


# ── CSV merge ─────────────────────────────────────────────────────────────────

def merge_list_into_games(games: list[dict], list_entries: list[dict], year: int) -> tuple[list[dict], int]:
    """Add any titles from list_entries not already in games. Returns (merged, added_count)."""
    existing = {g['title'].lower() for g in games}
    added = 0
    for entry in list_entries:
        if entry['title'].lower() not in existing:
            games.append({
                'title': entry['title'],
                'rating': 'unrated',
                'review': '',
                'url': entry.get('page_url') or '',
                'year_played': str(year),
                'release_year': '',
                'goty_categories': '',
            })
            existing.add(entry['title'].lower())
            added += 1
    return games, added


# ── Year tab computation ──────────────────────────────────────────────────────

HISTORIC_START_YEAR = 2024
AWARD_ONLY_CUTOFF_YEAR = 1999


def compute_year_tabs(games: list[dict], played_years: list[int],
                       historic_start_year: int = HISTORIC_START_YEAR,
                       award_only_cutoff_year: int = AWARD_ONLY_CUTOFF_YEAR
                       ) -> tuple[list[int], dict[int, str]]:
    """Combine played_years with historic GOTY-only tabs derived from games'
    release_year (historic_start_year down to the earliest release year
    present). Mode is based purely on year, regardless of whether it was
    played: years after historic_start_year get 'full' (tier/list/goty);
    years <= historic_start_year get 'goty' (full award grid, no tier/list)
    down to award_only_cutoff_year, below which they get 'goty-award'
    (GOTY slot only). Returns (years_sorted_desc, year_modes).
    """
    played_years = list(played_years)
    release_years_present = [
        int(g['release_year']) for g in games if g.get('release_year', '').strip().isdigit()
    ]
    if release_years_present:
        earliest_release_year = min(release_years_present)
        historic_years = [
            yr for yr in range(historic_start_year, earliest_release_year - 1, -1)
            if yr not in played_years
        ]
    else:
        historic_years = []

    years = sorted(set(played_years) | set(historic_years), reverse=True)
    year_modes = {}
    for yr in years:
        if yr > historic_start_year:
            year_modes[yr] = 'full'
        elif yr <= award_only_cutoff_year:
            year_modes[yr] = 'goty-award'
        else:
            year_modes[yr] = 'goty'
    return years, year_modes


# ── HTML generation ───────────────────────────────────────────────────────────

def generate_html(games: list[dict], covers: dict[str, str | None],
                  title: str = "Game Log",
                  page_urls: dict[str, str] | None = None,
                  years: list[int] | None = None,
                  year_modes: dict[int, str] | None = None) -> str:

    page_urls = page_urls or {}

    def cover_src(value: str) -> str:
        """Normalize a cover value to a forward-slash URL relative to the HTML
        file. Local cover files (whether stored as a relative 'covers/slug.jpg'
        or an absolute path like 'C:\\...\\covers\\slug.jpg') always live in a
        'covers' folder beside the page, so emit 'covers/<filename>'. Remote
        fallback URLs (http/https) are passed through unchanged."""
        if not value:
            return ''
        if value.startswith('http://') or value.startswith('https://'):
            return value
        return 'covers/' + os.path.basename(value)

    # Attach cover and url to each game
    games_with_meta = []
    for g in games:
        entry = dict(g)
        entry['cover'] = cover_src(covers.get(g['title']) or '')
        entry['url'] = g.get('url') or page_urls.get(g['title']) or ''
        entry['release_year'] = g.get('release_year') or ''
        cats = (g.get('goty_categories') or '').strip()
        entry['categories'] = [c for c in cats.split(';') if c]
        del entry['goty_categories']
        games_with_meta.append(entry)

    # Determine year list (fallback: derive from game data)
    if years:
        years_sorted = sorted(years, reverse=True)
    else:
        year_set: set[int] = set()
        for g in games_with_meta:
            yr = g.get('year_played', '').strip()
            if yr.isdigit():
                year_set.add(int(yr))
        years_sorted = sorted(year_set, reverse=True)

    # Group by year (fall back to release_year for games with no year_played,
    # e.g. ones merged in from the full library scrape) so they're still
    # discoverable as GOTY candidates for their release year.
    games_by_year: dict[int, list] = {yr: [] for yr in years_sorted}
    for g in games_with_meta:
        yr_str = g.get('year_played', '').strip()
        if yr_str.isdigit():
            yr = int(yr_str)
        else:
            ry_str = g.get('release_year', '').strip()
            yr = int(ry_str) if ry_str.isdigit() else None
        if yr is not None and yr in games_by_year:
            games_by_year[yr].append(g)

    games_by_year_json = json.dumps(games_by_year, ensure_ascii=False)
    years_json = json.dumps(years_sorted)
    goty_categories_json = json.dumps(GOTY_CATEGORIES, ensure_ascii=False)
    year_modes_json = json.dumps(year_modes or {}, ensure_ascii=False)

    rating_css_vars = '\n'.join(
        f'    --color-{r}: {c};' for r, c in RATING_COLORS.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <link rel="icon" type="image/png" href="GameRaterLogo.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
  <script src="html2canvas.min.js"></script>
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

    html {{ scrollbar-color: var(--accent) transparent; scrollbar-width: thin; }}
    ::-webkit-scrollbar {{ width: 10px; height: 10px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: var(--accent); border-radius: 6px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #bfa0ff; }}

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
      padding: 2.5rem 2rem 1.5rem;
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

    .year-label {{
      font-family: 'Syne', sans-serif;
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--accent);
      margin-top: 0.3rem;
      letter-spacing: -0.01em;
    }}

    /* ── Year tabs ── */
    .year-tabs {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 0 2rem;
      display: flex;
      flex-direction: column;
      gap: 0;
      border-bottom: 1px solid var(--border);
    }}

    .year-tabs-row {{
      display: flex;
      gap: 0;
      align-items: flex-end;
      flex-wrap: wrap;
    }}

    .year-tab {{
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      color: var(--text-muted);
      padding: 0.6rem 1.2rem;
      font-family: 'Syne', sans-serif;
      font-size: 1rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s ease;
      letter-spacing: 0.02em;
    }}

    .year-tab:hover {{ color: var(--text); }}

    .year-tab.active {{
      color: var(--accent);
      border-bottom-color: var(--accent);
    }}

    /* ── Toolbar (filter bar + view toggle) ── */
    .toolbar {{
      max-width: 1100px;
      margin: 1.25rem auto 0;
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
      margin: 0;
      text-align: left;
      font-size: 0.8rem;
      color: var(--text-muted);
    }}

    .view-toggle-col {{
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 0.35rem;
      flex-shrink: 0;
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

    .game-row.clickable {{ cursor: pointer; }}
    .game-row.clickable:hover .game-title {{ color: var(--accent); }}

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

    /* ── Hover dim + title overlay (shared across List/Tier/GOTY covers) ── */
    .cover-hover {{ position: relative; }}

    .cover-hover img,
    .cover-hover .cover-placeholder,
    .cover-hover .tier-cover-placeholder,
    .cover-hover .goty-slot-cover,
    .cover-hover .goty-slot-placeholder {{
      transition: filter 0.15s ease;
    }}

    .cover-hover:hover img,
    .cover-hover:hover .cover-placeholder,
    .cover-hover:hover .tier-cover-placeholder,
    .cover-hover:hover .goty-slot-cover,
    .cover-hover:hover .goty-slot-placeholder {{
      filter: brightness(0.35);
    }}

    .cover-hover-title {{
      display: none;
      position: absolute;
      inset: 0;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 0.3rem;
      color: #fff;
      font-family: 'Syne', sans-serif;
      font-weight: 700;
      font-size: 0.7rem;
      line-height: 1.15;
      overflow: hidden;
      pointer-events: none;
      z-index: 5;
    }}

    .cover-hover:hover .cover-hover-title {{ display: flex; }}

    .goty-slot-goty .cover-hover-title {{ font-size: 0.95rem; }}

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
      transition: color 0.15s ease;
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
      cursor: grab;
    }}

    .tier-cover-item:active {{ cursor: grabbing; }}

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

    .tier-empty {{
      padding: 1rem;
      color: var(--text-muted);
      font-size: 0.82rem;
      font-style: italic;
      align-self: center;
    }}

    .tier-cover-item.dragging {{
      opacity: 0.35;
      outline: 2px dashed var(--accent);
      outline-offset: 2px;
      border-radius: 4px;
    }}

    .tier-covers.drag-over {{
      background: color-mix(in srgb, var(--tier-color) 8%, transparent);
      outline: 2px dashed var(--tier-color);
      outline-offset: -4px;
      border-radius: 4px;
    }}

    .tier-cover-item.drop-before {{
      outline: 2px solid var(--accent);
      outline-offset: 2px;
      border-radius: 4px;
    }}

    /* ── GOTY view ── */
    .goty-view {{
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }}

    .goty-slots {{
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }}

    .goty-row-main {{
      display: flex;
      justify-content: center;
    }}

    .goty-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1.25rem;
    }}

    .goty-slot {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.5rem;
    }}

    .goty-slot-art {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.25rem;
    }}

    .goty-slot-cover-box {{
      position: relative;
      cursor: grab;
    }}

    .goty-slot-cover-box.dragging {{
      opacity: 0.35;
      outline: 2px dashed var(--accent);
      outline-offset: 2px;
      border-radius: 6px;
    }}

    .goty-slot-cover {{
      display: block;
      object-fit: cover;
      border-radius: 6px;
      border: 1px solid var(--border);
    }}

    .goty-slot-goty .goty-slot-cover {{
      width: 220px;
      height: 293px;
    }}

    .goty-grid .goty-slot-cover {{
      width: 130px;
      height: 173px;
    }}

    .goty-slot-placeholder {{
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--surface2);
      font-family: 'Syne', sans-serif;
      font-weight: 800;
      color: var(--text-muted);
      font-size: 2rem;
    }}

    .goty-slot-empty {{
      width: 130px;
      height: 173px;
      border: 2px dashed var(--border);
      border-radius: 6px;
      background: var(--surface);
    }}

    .goty-slot-goty .goty-slot-empty {{
      width: 220px;
      height: 293px;
    }}

    .goty-slot.drag-over .goty-slot-empty,
    .goty-slot.drag-over .goty-slot-cover-box {{
      outline: 2px dashed var(--accent);
      outline-offset: 2px;
      border-radius: 6px;
    }}

    .goty-remove-btn {{
      display: none;
      position: absolute;
      top: -8px;
      right: -8px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      border: 1px solid var(--border);
      background: #0f0f13;
      color: var(--text);
      font-size: 0.95rem;
      line-height: 1;
      cursor: pointer;
      align-items: center;
      justify-content: center;
      z-index: 6;
    }}

    .goty-slot-cover-box:hover .goty-remove-btn {{ display: flex; }}

    .goty-remove-btn:hover {{ background: var(--surface2); color: var(--accent); }}

    .goty-slot-label {{
      font-family: 'Syne', sans-serif;
      font-weight: 700;
      color: var(--text);
      text-align: center;
      font-size: 0.85rem;
    }}

    .goty-slot-goty .goty-slot-label {{
      font-size: 1.1rem;
    }}

    .goty-candidates-heading {{
      font-family: 'Syne', sans-serif;
      font-weight: 700;
      font-size: 1rem;
      color: var(--text-dim);
      border-top: 1px solid var(--border);
      padding-top: 1.25rem;
    }}

    .goty-candidates {{
      background: transparent;
      padding: 0;
    }}

    /* ── Off-screen container used to rasterize an export image ── */
    .export-capture {{
      position: fixed;
      left: -100000px;
      top: 0;
      background: var(--bg);
      padding: 28px;
      box-sizing: border-box;
    }}

    .export-capture .export-title {{
      font-family: 'Syne', sans-serif;
      font-size: 1.5rem;
      font-weight: 800;
      color: var(--text);
      margin-bottom: 18px;
    }}

    .export-capture .goty-slots {{ margin-top: 6px; }}

    /* ── Responsive ── */
    @media (max-width: 600px) {{
      header, .year-tabs, .game-count, .toolbar, main {{ padding-left: 1rem; padding-right: 1rem; }}
      .game-body {{ padding: 0.75rem 0.9rem; }}
      .tier-label-col {{ width: 110px; }}
      .tier-rating-img {{ width: 64px; height: 64px; }}
      .tier-cover-item {{ width: 66px; }}
      .tier-cover-item img, .tier-cover-placeholder {{ width: 66px; height: 88px; }}
      .goty-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .goty-slot-goty .goty-slot-cover, .goty-slot-goty .goty-slot-empty {{ width: 150px; height: 200px; }}
      .goty-grid .goty-slot-cover, .goty-grid .goty-slot-empty {{ width: 96px; height: 128px; }}
    }}
  </style>
</head>
<body>

<div class="year-tabs" id="year-tabs" style="display:none;"></div>

<div class="toolbar">
  <div class="view-toggle-col" style="display:none;">
    <div class="view-toggle" style="display:none;">
      <button class="view-btn active" id="btn-tier" onclick="setView('tier')" title="Tier view">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="1" y="2" width="14" height="3.5" rx="1" fill="currentColor" opacity="0.9"/><rect x="1" y="6.5" width="14" height="3" rx="1" fill="currentColor" opacity="0.65"/><rect x="1" y="10.5" width="14" height="3" rx="1" fill="currentColor" opacity="0.4"/></svg>
      </button>
      <button class="view-btn" id="btn-list" onclick="setView('list')" title="List view">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="5" y="2" width="9" height="2" rx="1" fill="currentColor"/><rect x="5" y="7" width="9" height="2" rx="1" fill="currentColor"/><rect x="5" y="12" width="9" height="2" rx="1" fill="currentColor"/><rect x="2" y="2" width="2" height="2" rx="0.5" fill="currentColor"/><rect x="2" y="7" width="2" height="2" rx="0.5" fill="currentColor"/><rect x="2" y="12" width="2" height="2" rx="0.5" fill="currentColor"/></svg>
      </button>
      <button class="view-btn" id="btn-goty" onclick="setView('goty')" title="GOTY view">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M5 1.5h6v3.5a3 3 0 0 1-6 0V1.5Z" fill="currentColor"/><path d="M5 2.2H2.7a1 1 0 0 0-1 1.1c.15 1.5 1 2.7 2.6 3.2" stroke="currentColor" stroke-width="1.1" fill="none" stroke-linecap="round"/><path d="M11 2.2h2.3a1 1 0 0 1 1 1.1c-.15 1.5-1 2.7-2.6 3.2" stroke="currentColor" stroke-width="1.1" fill="none" stroke-linecap="round"/><rect x="7" y="8.5" width="2" height="2.3" fill="currentColor"/><path d="M4.5 14.5c0-1.4 1.5-2.3 3.5-2.3s3.5 0.9 3.5 2.3v.3h-7v-.3Z" fill="currentColor"/></svg>
      </button>
    </div>
    <p class="game-count" id="game-count"></p>
  </div>
  <div class="filter-bar" id="filter-bar">
    <span class="filter-label">Filter</span>
    <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
    <button class="filter-btn" onclick="setFilter('fantastic', this)">Fantastic</button>
    <button class="filter-btn" onclick="setFilter('great', this)">Great</button>
    <button class="filter-btn" onclick="setFilter('good', this)">Good</button>
    <button class="filter-btn" onclick="setFilter('okay', this)">Okay</button>
    <button class="filter-btn" onclick="setFilter('mixed', this)">Mixed</button>
    <button class="filter-btn" onclick="setFilter('lame', this)">Lame</button>
    <button class="filter-btn" onclick="setFilter('unrated', this)">Unrated</button>
  </div>
</div>

<main>
  <div class="game-list" id="game-list" style="display:none;"></div>
  <div class="tier-view" id="tier-view"></div>
  <div class="goty-view" id="goty-view" style="display:none;"></div>
</main>

<script>
const YEARS = {years_json};
const GAMES_BY_YEAR = {games_by_year_json};
const GOTY_CATEGORIES = {goty_categories_json};
const YEAR_MODES = {year_modes_json};

const RATING_COLORS = {{
  fantastic: '#d4a017',
  great:     '#7c3aed',
  good:      '#2563eb',
  okay:      '#c2620a',
  lame:      '#7c5c3a',
  mixed:     '#6b7280',
  unrated:   '#3a3a4a',
}};

const RATING_LABELS = {{
  fantastic: 'Fantastic',
  great:     'Great',
  good:      'Good',
  okay:      'Okay',
  lame:      'Lame',
  mixed:     'Mixed',
  unrated:   'Unrated',
}};

const ORDER = ['fantastic','great','good','mixed','okay','lame'];
const ALL_RATINGS = [...ORDER, 'unrated'];

// ── Mutable state ─────────────────────────────────────
// ALL_STATE[year][rating] = [{{title, cover, review, rating, url}}]
let ALL_STATE = {{}};
let currentYear = YEARS[0];
let state = null;  // reference into ALL_STATE[currentYear]

function initAllState() {{
  YEARS.forEach(yr => {{
    ALL_STATE[yr] = {{}};
    ALL_RATINGS.forEach(r => ALL_STATE[yr][r] = []);
    (GAMES_BY_YEAR[yr] || []).forEach(g => {{
      const r = ALL_RATINGS.includes(g.rating) ? g.rating : 'unrated';
      ALL_STATE[yr][r].push({{
        title:        g.title,
        cover:        g.cover  || '',
        review:       g.review || '',
        rating:       r,
        url:          g.url    || '',
        release_year: g.release_year || '',
        categories:   Array.isArray(g.categories) ? g.categories.slice() : [],
      }});
    }});
  }});
  state = ALL_STATE[currentYear];
}}

// ── Year tabs ─────────────────────────────────────────
const YEAR_TABS_PER_ROW = 12;

function buildYearTabs() {{
  const container = document.getElementById('year-tabs');
  container.innerHTML = '';
  let row = null;
  YEARS.forEach((yr, i) => {{
    if (i % YEAR_TABS_PER_ROW === 0) {{
      row = document.createElement('div');
      row.className = 'year-tabs-row';
      container.appendChild(row);
    }}
    const btn = document.createElement('button');
    btn.className = 'year-tab' + (yr === currentYear ? ' active' : '');
    btn.textContent = String(yr);
    btn.dataset.year = yr;
    btn.addEventListener('click', () => setYear(yr));
    row.appendChild(btn);
  }});
}}

function yearMode(yr) {{ return YEAR_MODES[yr] || 'full'; }}

function applyViewAvailability() {{
  const restricted = yearMode(currentYear) !== 'full';
  document.getElementById('btn-tier').style.display = restricted ? 'none' : '';
  document.getElementById('btn-list').style.display = restricted ? 'none' : '';
}}

function setYear(yr) {{
  currentYear = yr;
  state = ALL_STATE[yr];
  document.querySelectorAll('.year-tab').forEach(b =>
    b.classList.toggle('active', parseInt(b.dataset.year) === yr));
  applyViewAvailability();
  setView(yearMode(yr) !== 'full' ? 'goty' : currentView);
}}

// ── Dirty tracking + autosave ─────────────────────────
let dirty = false;
let autosaveTimer = null;

function markDirty() {{
  dirty = true;
  if (autosaveTimer) clearTimeout(autosaveTimer);
  // Debounce so a burst of changes (e.g. a drag) saves once it settles.
  autosaveTimer = setTimeout(saveCSV, 500);
}}

// ── CSV export (all years) ────────────────────────────
function buildCSV() {{
  const rows = [['title', 'rating', 'review', 'url', 'year_played', 'release_year', 'goty_categories']];
  YEARS.forEach(yr => {{
    const yrState = ALL_STATE[yr];
    ALL_RATINGS.forEach(r => {{
      (yrState[r] || []).forEach(g => {{
        const esc = s => {{
          s = s || '';
          return s.includes(',') || s.includes('"') || s.includes('\\n')
            ? `"${{s.replace(/"/g, '""')}}"` : s;
        }};
        rows.push([esc(g.title), r, esc(g.review), esc(g.url), String(yr),
                   esc(g.release_year), esc((g.categories || []).join(';'))]);
      }});
    }});
  }});
  return rows.map(r => r.join(',')).join('\\n');
}}

async function saveCSV() {{
  const csv = buildCSV();
  const api = pyapi();
  if (api && api.save_csv) {{
    try {{
      const result = await api.save_csv(csv);
      if (result && result.ok) dirty = false;
    }} catch (e) {{}}
    return;
  }}
  // Fallback: local save server (e.g. the page opened standalone in a browser)
  try {{
    const resp = await fetch('http://127.0.0.1:57432/save-csv', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'text/csv' }},
      body: csv,
    }});
    const result = await resp.json();
    if (result && result.ok) dirty = false;
  }} catch (_) {{}}
}}

// ── Drag state ────────────────────────────────────────
let dragGame = null;
let dragEl   = null;

let autoScrollRAF = null;

function startAutoScroll(clientY) {{
  const ZONE = 80, SPEED = 12;
  cancelAutoScroll();
  function tick() {{
    const vh = window.innerHeight;
    if (clientY < ZONE) {{
      window.scrollBy(0, -SPEED * (1 - clientY / ZONE));
    }} else if (clientY > vh - ZONE) {{
      window.scrollBy(0, SPEED * (1 - (vh - clientY) / ZONE));
    }}
    autoScrollRAF = requestAnimationFrame(tick);
  }}
  autoScrollRAF = requestAnimationFrame(tick);
}}

function cancelAutoScroll() {{
  if (autoScrollRAF) {{ cancelAnimationFrame(autoScrollRAF); autoScrollRAF = null; }}
}}

document.addEventListener('dragover', e => {{ if (dragGame) startAutoScroll(e.clientY); }});
document.addEventListener('dragend',  () => cancelAutoScroll());

function escapeHtml(str) {{
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function getInitial(title) {{
  return title.trim()[0]?.toUpperCase() ?? '?';
}}

// The rater is hosted in an iframe inside the launcher window. pywebview's
// JS API lives on the top frame, so reach it via window.parent (same origin).
function pyapi() {{
  if (window.pywebview && window.pywebview.api) return window.pywebview.api;
  try {{
    if (window.parent && window.parent.pywebview && window.parent.pywebview.api) {{
      return window.parent.pywebview.api;
    }}
  }} catch (e) {{}}
  return null;
}}

function openExternal(url) {{
  if (!url) return;
  const api = pyapi();
  if (api && api.open_external) {{
    api.open_external(url);
  }} else {{
    window.open(url, '_blank', 'noopener');
  }}
}}

// ── List view ─────────────────────────────────────────
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
  row.className = 'game-row' + (game.url ? ' clickable' : '');
  row.dataset.rating = game.rating;
  row.style.setProperty('--row-accent', color);
  if (game.url) row.addEventListener('click', () => openExternal(game.url));
  row.innerHTML = `
    <div class="game-cover-wrap cover-hover">${{coverHtml}}<span class="cover-hover-title">${{escapeHtml(game.title)}}</span></div>
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
function makeCoverItem(game, rating) {{
  const item = document.createElement('div');
  item.className = 'tier-cover-item cover-hover';
  item.draggable = true;
  item.dataset.title  = game.title;
  item.dataset.rating = rating;

  const tooltip = document.createElement('span');
  tooltip.className   = 'cover-hover-title';
  tooltip.textContent = game.title;

  const coverEl = game.cover
    ? (() => {{
        const i = document.createElement('img');
        i.src      = game.cover;
        i.alt      = game.title;
        i.draggable = false;
        i.onerror  = function() {{
          this.outerHTML = `<div class="tier-cover-placeholder">${{getInitial(game.title)}}</div>`;
        }};
        return i;
      }})()
    : (() => {{
        const d = document.createElement('div');
        d.className   = 'tier-cover-placeholder';
        d.textContent = getInitial(game.title);
        return d;
      }})();

  item.appendChild(tooltip);
  item.appendChild(coverEl);

  // Click opens Backloggd page, but not if a drag just finished
  let wasDragged = false;
  item.addEventListener('dragstart', e => {{
    wasDragged = true;
    dragGame = {{ title: game.title, fromRating: rating }};
    dragEl   = item;
    setTimeout(() => item.classList.add('dragging'), 0);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', game.title);
  }});
  item.addEventListener('click', () => {{
    if (wasDragged) {{ wasDragged = false; return; }}
    if (game.url) openExternal(game.url);
  }});
  item.addEventListener('dragend', () => {{
    item.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    document.querySelectorAll('.drop-before').forEach(el => el.classList.remove('drop-before'));
    cancelAutoScroll();
    dragGame = null;
    dragEl   = null;
  }});

  item.addEventListener('dragover', e => {{
    if (!dragGame) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.drop-before').forEach(el => el.classList.remove('drop-before'));
    const rect = item.getBoundingClientRect();
    if (e.clientX < rect.left + rect.width / 2) item.classList.add('drop-before');
  }});
  item.addEventListener('dragleave', () => item.classList.remove('drop-before'));
  item.addEventListener('drop', e => {{
    e.preventDefault();
    e.stopPropagation();
    if (!dragGame || dragGame.title === game.title) return;
    const toRating    = rating;
    const rect        = item.getBoundingClientRect();
    const insertBefore = e.clientX < rect.left + rect.width / 2;
    const srcList = state[dragGame.fromRating];
    const srcIdx  = srcList.findIndex(g => g.title === dragGame.title);
    const [moved] = srcList.splice(srcIdx, 1);
    moved.rating  = toRating;
    const dstList = state[toRating];
    const dstIdx  = dstList.findIndex(g => g.title === game.title);
    dstList.splice(insertBefore ? dstIdx : dstIdx + 1, 0, moved);
    markDirty();
    renderTiers();
  }});

  return item;
}}

function buildTierRow(rating) {{
  const color = RATING_COLORS[rating] || '#888';
  const label = RATING_LABELS[rating] || rating;
  const games = state[rating] || [];

  const row = document.createElement('div');
  row.className = 'tier-row';
  row.dataset.tierRating = rating;
  row.style.setProperty('--tier-color', color);

  const labelCol = document.createElement('div');
  labelCol.className = 'tier-label-col';
  if (rating === 'unrated') {{
    const span = document.createElement('span');
    span.className   = 'tier-rating-pill';
    span.textContent = label;
    labelCol.appendChild(span);
  }} else {{
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

  const coversDiv = document.createElement('div');
  coversDiv.className = 'tier-covers';
  coversDiv.dataset.dropRating = rating;

  if (games.length === 0) {{
    const empty = document.createElement('span');
    empty.className   = 'tier-empty';
    empty.textContent = 'None';
    coversDiv.appendChild(empty);
  }} else {{
    games.forEach(game => coversDiv.appendChild(makeCoverItem(game, rating)));
  }}

  coversDiv.addEventListener('dragover', e => {{
    if (!dragGame) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    coversDiv.classList.add('drag-over');
  }});
  coversDiv.addEventListener('dragleave', e => {{
    if (!coversDiv.contains(e.relatedTarget)) coversDiv.classList.remove('drag-over');
  }});
  coversDiv.addEventListener('drop', e => {{
    e.preventDefault();
    coversDiv.classList.remove('drag-over');
    if (!dragGame) return;
    if (e.target.closest('.tier-cover-item')) return;
    const srcList = state[dragGame.fromRating];
    const srcIdx  = srcList.findIndex(g => g.title === dragGame.title);
    if (srcIdx === -1) return;
    const [moved] = srcList.splice(srcIdx, 1);
    moved.rating  = rating;
    state[rating].push(moved);
    markDirty();
    renderTiers();
  }});

  row.appendChild(coversDiv);
  return row;
}}

// ── View & filter state ───────────────────────────────
let currentFilter = 'all';
let currentView   = 'tier';

function setView(view) {{
  currentView = view;
  document.getElementById('btn-list').classList.toggle('active', view === 'list');
  document.getElementById('btn-tier').classList.toggle('active', view === 'tier');
  document.getElementById('btn-goty').classList.toggle('active', view === 'goty');
  document.getElementById('filter-bar').style.display = view === 'list' ? '' : 'none';
  document.getElementById('game-list').style.display = view === 'list' ? '' : 'none';
  document.getElementById('tier-view').style.display = view === 'tier' ? '' : 'none';
  document.getElementById('goty-view').style.display  = view === 'goty' ? '' : 'none';
  if (view === 'list') renderList();
  else if (view === 'tier') renderTiers();
  else renderGoty();
}}

function setFilter(filter, btn) {{
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderList();
}}

function renderList() {{
  const list    = document.getElementById('game-list');
  const countEl = document.getElementById('game-count');
  list.innerHTML = '';
  const allGames = ALL_RATINGS.flatMap(r => state[r]);
  const filtered = currentFilter === 'all'
    ? allGames
    : allGames.filter(g => g.rating === currentFilter);
  if (filtered.length === 0) {{
    list.innerHTML = '<div class="empty">No games with this rating yet.</div>';
    countEl.textContent = '';
    return;
  }}
  const sorted = [...filtered].sort((a, b) =>
    ALL_RATINGS.indexOf(a.rating) - ALL_RATINGS.indexOf(b.rating));
  countEl.textContent = `${{sorted.length}} game${{sorted.length !== 1 ? 's' : ''}}`;
  sorted.forEach(game => list.appendChild(buildRow(game)));
}}

function renderTiers() {{
  const container = document.getElementById('tier-view');
  container.innerHTML = '';
  ORDER.forEach(rating => container.appendChild(buildTierRow(rating)));
  const divider = document.createElement('div');
  divider.style.cssText = 'height:1px; background:var(--border); margin:8px 0;';
  container.appendChild(divider);
  container.appendChild(buildTierRow('unrated'));
  const total = ALL_RATINGS.reduce((n, r) => n + (state[r] || []).length, 0);
  document.getElementById('game-count').textContent =
    `${{total}} game${{total !== 1 ? 's' : ''}}`;
}}

// ── GOTY view ─────────────────────────────────────────
let gotyDragGame = null;

document.addEventListener('dragover', e => {{ if (gotyDragGame) startAutoScroll(e.clientY); }});
document.addEventListener('dragend',  () => {{ if (gotyDragGame) cancelAutoScroll(); }});

function allGamesFlat() {{
  return YEARS.flatMap(yr => ALL_RATINGS.flatMap(r => ALL_STATE[yr][r] || []));
}}

function findGameByTitle(title) {{
  return allGamesFlat().find(g => g.title === title) || null;
}}

function findCategoryHolder(key, year) {{
  return allGamesFlat().find(g =>
    parseInt(g.release_year, 10) === year && (g.categories || []).includes(key)) || null;
}}

function assignCategory(key, title) {{
  const game = findGameByTitle(title);
  if (!game) return;
  const holder = findCategoryHolder(key, currentYear);
  if (holder && holder.title !== game.title) {{
    holder.categories = holder.categories.filter(c => c !== key);
  }}
  if (!game.categories.includes(key)) game.categories.push(key);
  markDirty();
  renderGoty();
}}

function moveCategory(key, fromCategory, title) {{
  if (key === fromCategory) return;
  const game = findGameByTitle(title);
  if (!game) return;
  game.categories = game.categories.filter(c => c !== fromCategory);
  const holder = findCategoryHolder(key, currentYear);
  if (holder && holder.title !== game.title) {{
    holder.categories = holder.categories.filter(c => c !== key);
  }}
  if (!game.categories.includes(key)) game.categories.push(key);
  markDirty();
  renderGoty();
}}

function removeCategory(key, title) {{
  const game = findGameByTitle(title);
  if (!game) return;
  game.categories = game.categories.filter(c => c !== key);
  markDirty();
  renderGoty();
}}

function buildGotySlot(cat, large) {{
  const slot = document.createElement('div');
  slot.className = 'goty-slot' + (large ? ' goty-slot-goty' : '');

  const artWrap = document.createElement('div');
  artWrap.className = 'goty-slot-art';

  const holder = findCategoryHolder(cat.key, currentYear);

  const artBox = document.createElement('div');
  artBox.className = 'goty-slot-cover-box';

  if (holder) {{
    artBox.classList.add('cover-hover');
    let wasDragged = false;
    const img = holder.cover
      ? (() => {{
          const i = document.createElement('img');
          i.className = 'goty-slot-cover';
          i.src = holder.cover;
          i.alt = holder.title;
          i.draggable = false;
          i.onerror = function() {{
            this.outerHTML = `<div class="goty-slot-cover goty-slot-placeholder">${{getInitial(holder.title)}}</div>`;
          }};
          return i;
        }})()
      : (() => {{
          const d = document.createElement('div');
          d.className = 'goty-slot-cover goty-slot-placeholder';
          d.textContent = getInitial(holder.title);
          return d;
        }})();
    artBox.draggable = true;
    artBox.appendChild(img);

    const hoverTitle = document.createElement('span');
    hoverTitle.className   = 'cover-hover-title';
    hoverTitle.textContent = holder.title;
    artBox.appendChild(hoverTitle);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'goty-remove-btn';
    removeBtn.title = 'Remove from this award';
    removeBtn.innerHTML = '&times;';
    removeBtn.addEventListener('click', e => {{
      e.stopPropagation();
      removeCategory(cat.key, holder.title);
    }});
    artBox.appendChild(removeBtn);

    artBox.addEventListener('dragstart', e => {{
      wasDragged = true;
      gotyDragGame = {{ title: holder.title, mode: 'slot', fromCategory: cat.key }};
      setTimeout(() => artBox.classList.add('dragging'), 0);
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', holder.title);
    }});
    artBox.addEventListener('dragend', () => {{
      artBox.classList.remove('dragging');
      gotyDragGame = null;
    }});
    artBox.addEventListener('click', () => {{
      if (wasDragged) {{ wasDragged = false; return; }}
      if (holder.url) openExternal(holder.url);
    }});
  }} else {{
    artBox.classList.add('goty-slot-empty');
  }}

  artWrap.appendChild(artBox);
  slot.appendChild(artWrap);

  const label = document.createElement('div');
  label.className = 'goty-slot-label';
  label.textContent = cat.label;
  slot.appendChild(label);

  slot.addEventListener('dragover', e => {{
    if (!gotyDragGame) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    slot.classList.add('drag-over');
  }});
  slot.addEventListener('dragleave', e => {{
    if (!slot.contains(e.relatedTarget)) slot.classList.remove('drag-over');
  }});
  slot.addEventListener('drop', e => {{
    e.preventDefault();
    slot.classList.remove('drag-over');
    if (!gotyDragGame) return;
    if (gotyDragGame.mode === 'candidate') assignCategory(cat.key, gotyDragGame.title);
    else if (gotyDragGame.mode === 'slot') moveCategory(cat.key, gotyDragGame.fromCategory, gotyDragGame.title);
    gotyDragGame = null;
  }});

  return slot;
}}

function buildGotyCandidate(game) {{
  const item = document.createElement('div');
  item.className = 'tier-cover-item cover-hover';
  item.draggable = true;

  const tooltip = document.createElement('span');
  tooltip.className   = 'cover-hover-title';
  tooltip.textContent = game.title;

  const coverEl = game.cover
    ? (() => {{
        const i = document.createElement('img');
        i.src = game.cover;
        i.alt = game.title;
        i.draggable = false;
        i.onerror = function() {{
          this.outerHTML = `<div class="tier-cover-placeholder">${{getInitial(game.title)}}</div>`;
        }};
        return i;
      }})()
    : (() => {{
        const d = document.createElement('div');
        d.className   = 'tier-cover-placeholder';
        d.textContent = getInitial(game.title);
        return d;
      }})();

  item.appendChild(tooltip);
  item.appendChild(coverEl);

  let wasDragged = false;
  item.addEventListener('dragstart', e => {{
    wasDragged = true;
    gotyDragGame = {{ title: game.title, mode: 'candidate' }};
    setTimeout(() => item.classList.add('dragging'), 0);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', game.title);
  }});
  item.addEventListener('dragend', () => {{
    item.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    cancelAutoScroll();
    gotyDragGame = null;
  }});
  item.addEventListener('click', () => {{
    if (wasDragged) {{ wasDragged = false; return; }}
    if (game.url) openExternal(game.url);
  }});

  return item;
}}

function renderGoty() {{
  const container = document.getElementById('goty-view');
  container.innerHTML = '';

  const slotsWrap = document.createElement('div');
  slotsWrap.className = 'goty-slots';

  const gotyCat = GOTY_CATEGORIES[0];
  const gotyRow = document.createElement('div');
  gotyRow.className = 'goty-row-main';
  gotyRow.appendChild(buildGotySlot(gotyCat, true));
  slotsWrap.appendChild(gotyRow);

  if (yearMode(currentYear) !== 'goty-award') {{
    const grid = document.createElement('div');
    grid.className = 'goty-grid';
    GOTY_CATEGORIES.slice(1).forEach(cat => grid.appendChild(buildGotySlot(cat, false)));
    slotsWrap.appendChild(grid);
  }}

  container.appendChild(slotsWrap);

  const heading = document.createElement('div');
  heading.className = 'goty-candidates-heading';
  heading.textContent = 'Candidates';
  container.appendChild(heading);

  const candidatesWrap = document.createElement('div');
  candidatesWrap.className = 'goty-candidates tier-covers';

  const candidates = allGamesFlat()
    .filter(g => parseInt(g.release_year, 10) === currentYear)
    .sort((a, b) => ALL_RATINGS.indexOf(a.rating) - ALL_RATINGS.indexOf(b.rating));

  if (candidates.length === 0) {{
    const empty = document.createElement('span');
    empty.className   = 'tier-empty';
    empty.textContent = 'No games released in ' + currentYear + ' on this list.';
    candidatesWrap.appendChild(empty);
  }} else {{
    candidates.forEach(game => candidatesWrap.appendChild(buildGotyCandidate(game)));
  }}

  container.appendChild(candidatesWrap);

  document.getElementById('game-count').textContent =
    `${{candidates.length}} candidate${{candidates.length !== 1 ? 's' : ''}}`;
}}

// ── Export the current view to a PNG (rasterized with html2canvas) ────
// Builds a clean off-screen copy of just the tiers (Tier view, unrated
// excluded) or the award slots (GOTY view, candidates excluded) for the
// current year, then hands the resulting PNG data URL back to the launcher.
async function exportImage() {{
  const view = currentView;
  if (view !== 'tier' && view !== 'goty') {{
    return {{ ok: false, error: 'unsupported-view' }};
  }}
  if (typeof html2canvas !== 'function') {{
    return {{ ok: false, error: 'html2canvas-missing' }};
  }}

  const refView = document.getElementById(view === 'tier' ? 'tier-view' : 'goty-view');
  const width = Math.max(refView ? refView.offsetWidth : 0, 640);

  const wrap = document.createElement('div');
  wrap.className = 'export-capture';
  wrap.style.width = width + 'px';

  const heading = document.createElement('div');
  heading.className = 'export-title';
  heading.textContent = (view === 'tier' ? 'Tier List' : 'Game of the Year') + ' — ' + currentYear;
  wrap.appendChild(heading);

  if (view === 'tier') {{
    // Rated tiers only — the "unrated" row is intentionally left out.
    const tiers = document.createElement('div');
    tiers.className = 'tier-view';
    ORDER.forEach(rating => tiers.appendChild(buildTierRow(rating)));
    wrap.appendChild(tiers);
  }} else {{
    // All award slots, without the candidates picker below them.
    const slotsWrap = document.createElement('div');
    slotsWrap.className = 'goty-slots';
    const gotyRow = document.createElement('div');
    gotyRow.className = 'goty-row-main';
    gotyRow.appendChild(buildGotySlot(GOTY_CATEGORIES[0], true));
    slotsWrap.appendChild(gotyRow);
    if (yearMode(currentYear) !== 'goty-award') {{
      const grid = document.createElement('div');
      grid.className = 'goty-grid';
      GOTY_CATEGORIES.slice(1).forEach(cat => grid.appendChild(buildGotySlot(cat, false)));
      slotsWrap.appendChild(grid);
    }}
    wrap.appendChild(slotsWrap);
  }}

  document.body.appendChild(wrap);
  try {{
    const bg = getComputedStyle(document.body).backgroundColor || '#0f0f13';
    const canvas = await html2canvas(wrap, {{
      backgroundColor: bg,
      scale: 2,
      useCORS: true,
      logging: false,
    }});
    return {{ ok: true, dataUrl: canvas.toDataURL('image/png'), view: view, year: String(currentYear) }};
  }} catch (e) {{
    return {{ ok: false, error: String(e) }};
  }} finally {{
    wrap.remove();
  }}
}}

// Bridge so the launcher sidebar (parent frame) can drive year/view selection
// and read the current state. The in-page year tabs / view toggle are hidden;
// these call the same setYear/setView functions that update everything.
window.raterBridge = {{
  getMeta: () => ({{
    years: YEARS,
    yearModes: YEAR_MODES,
    currentYear: currentYear,
    currentView: currentView,
    restricted: yearMode(currentYear) !== 'full',
  }}),
  setYear: (yr) => {{ setYear(yr); return window.raterBridge.getMeta(); }},
  setView: (v) => {{ setView(v); return window.raterBridge.getMeta(); }},
  exportImage: () => exportImage(),
}};

(function init() {{
  initAllState();
  buildYearTabs();
  applyViewAvailability();
  setView(yearMode(currentYear) !== 'full' ? 'goty' : 'tier');
}})();
</script>
</body>
</html>
"""


# ── Shared tail helpers (used by all three create_game_log_* scripts) ─────────

def fetch_release_years_and_update(games: list[dict], csv_path: str, log) -> None:
    """Fetch missing release years for games with a url, write csv if anything changed."""
    log("\nFetching release years...")
    release_years = asyncio.run(fetch_release_years(games))
    if release_years:
        for game in games:
            if game['title'] in release_years:
                game['release_year'] = release_years[game['title']]
        write_csv(csv_path, games)
        log(f"  CSV updated with release years → {csv_path}")


def fetch_covers_and_render(games: list[dict], cover_urls: dict[str, str], page_urls: dict[str, str],
                             played_years: list[int], out_path: str, covers_dir: str, log) -> dict:
    """Fetch cover art, compute year tabs, render and write the HTML. Returns a result dict."""
    log("\nFetching cover art...")
    covers = asyncio.run(fetch_all_covers(games, cover_urls, covers_dir=covers_dir))

    years, year_modes = compute_year_tabs(games, played_years)

    log(f"\nGenerating {out_path}...")
    html = generate_html(games, covers, page_urls=page_urls, years=years, year_modes=year_modes)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    log(f"Done → {out_path}")
    return {'years': years, 'covers_found': sum(1 for v in covers.values() if v), 'out_path': out_path}


def rebuild_html_from_csv(csv_path: str, covers_dir: str, out_path: str) -> None:
    """Regenerate gamelog.html from games.csv using only locally cached covers (no network)."""
    games = read_csv(csv_path)
    covers = asyncio.run(fetch_all_covers(games, list_cover_urls={}, covers_dir=covers_dir))
    played_years = [int(g['year_played']) for g in games if g.get('year_played', '').isdigit()]
    years, year_modes = compute_year_tabs(games, played_years)
    html = generate_html(games, covers, years=years, year_modes=year_modes)
    from pathlib import Path
    Path(out_path).write_text(html, encoding='utf-8')


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all_played_lists(csv_path: str, out_path: str, folder_url: str = BACKLOGGD_FOLDER_URL,
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

    all_cover_urls: dict[str, str] = {}
    all_page_urls:  dict[str, str] = {}
    added_total = 0
    csv_changed = False

    if year_lists:
        for year, list_url in year_lists:
            log(f"\nFetching games for {year}...")
            entries = asyncio.run(fetch_backloggd_list(list_url))
            if not entries:
                log(f"  Could not fetch list for {year}.")
                continue
            games, added = merge_list_into_games(games, entries, year=year)
            if added:
                log(f"  Added {added} new game(s) for {year}.")
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

    played_years = [yr for yr, _ in year_lists] if year_lists else []

    fetch_release_years_and_update(games, csv_path, log)
    result = fetch_covers_and_render(games, all_cover_urls, all_page_urls, played_years,
                                      out_path, covers_dir, log)

    log("")
    log("Tips:")
    log("  • Re-run any time to sync new games from Backloggd and refresh the page.")
    log("  • Edit games.csv to add ratings and reviews for unrated games.")
    log("  • Drop manual covers in a covers/ folder as <slug>.jpg to override")
    log("    Backloggd lookups (e.g. 'hollow-knight.jpg').")

    return {'added': added_total, 'csv_changed': csv_changed, **result}


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'gamelog.html'
    run_all_played_lists(csv_path, out_path, BACKLOGGD_FOLDER_URL)


if __name__ == '__main__':
    main()
