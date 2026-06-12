#!/usr/bin/env python3
"""
Game Ratings HTML Generator
Usage: python3 generate.py [input.csv] [output.html]
Defaults: games.csv -> index.html

Requires: pip install playwright && python3 -m playwright install chromium
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
}

RATING_COLORS = {
    'fantastic': '#d4a017',
    'great':     '#7c3aed',
    'good':      '#2563eb',
    'okay':      '#c2620a',
    'lame':      '#6b7280',
    'awful':     '#16a34a',
    'mixed':     '#7c5c3a',
}


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
            if rating not in VALID_RATINGS:
                print(f"  Warning: '{rating}' is not a valid rating for '{title}'. "
                      f"Valid: {', '.join(VALID_RATINGS)}. Defaulting to 'okay'.")
                rating = 'okay'

            games.append({'title': title, 'rating': rating, 'review': review})
    return games


def title_to_backloggd_slug(title: str) -> str:
    """Convert a game title to a Backloggd URL slug."""
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)
    return slug


async def fetch_cover_backloggd(page, title: str) -> str | None:
    """Try to find a game's cover image on Backloggd."""
    slug = title_to_backloggd_slug(title)
    url = f"https://www.backloggd.com/games/{slug}/"

    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)

        if response.status == 404:
            # Try the search page instead
            search_url = f"https://www.backloggd.com/search/games/{slug}/"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)

            # Click the first result
            first_result = await page.query_selector('.game-cover, .card-img, a.game-link img')
            if first_result:
                await first_result.click()
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            else:
                return None

        # Look for the cover image — Backloggd uses img#cover or og:image
        cover_img = await page.query_selector('img#cover')
        if cover_img:
            src = await cover_img.get_attribute('src')
            if src and src.startswith('http'):
                return src

        # Fallback: og:image meta tag
        og = await page.query_selector('meta[property="og:image"]')
        if og:
            content = await og.get_attribute('content')
            if content and content.startswith('http') and 'backloggd' not in content.lower():
                # og:image on Backloggd game pages points to the cover art CDN
                return content
            elif content and content.startswith('http'):
                return content

        return None

    except Exception as e:
        print(f"    Error fetching {url}: {e}")
        return None


async def fetch_all_covers(games: list[dict]) -> dict[str, str | None]:
    """Launch a single browser and fetch all covers sequentially."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("\n  ⚠  Playwright not installed. Skipping cover art.")
        print("     To enable covers: pip install playwright && python3 -m playwright install chromium\n")
        return {}

    covers = {}
    print(f"  Fetching cover art from Backloggd ({len(games)} games)...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        for game in games:
            title = game['title']
            # Check for local cover first (skip network fetch if found)
            local_slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
            local_found = False
            for ext in ['jpg', 'jpeg', 'png', 'webp']:
                if Path(f"covers/{local_slug}.{ext}").exists():
                    covers[title] = f"covers/{local_slug}.{ext}"
                    print(f"  ✓ {title}: local cover")
                    local_found = True
                    break
            if local_found:
                continue

            print(f"  → {title}", end='', flush=True)
            cover_url = await fetch_cover_backloggd(page, title)
            if cover_url:
                covers[title] = cover_url
                print(f" ✓")
            else:
                covers[title] = None
                print(f" ✗ (not found)")

            # Polite delay between requests
            await asyncio.sleep(0.5)

        await browser.close()

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

    /* ── Filter bar ── */
    .filter-bar {{
      max-width: 1100px;
      margin: 1.5rem auto 0;
      padding: 0 2rem;
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
      align-items: center;
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

    /* ── Responsive ── */
    @media (max-width: 600px) {{
      header, .filter-bar, main {{ padding-left: 1rem; padding-right: 1rem; }}
      .game-body {{ padding: 0.75rem 0.9rem; }}
    }}
  </style>
</head>
<body>

<header>
  <h1>Game <span>Log</span></h1>
  <p class="header-meta" id="header-meta"></p>
</header>

<div class="filter-bar">
  <span class="filter-label">Filter</span>
  <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
  <button class="filter-btn" onclick="setFilter('fantastic', this)">Fantastic</button>
  <button class="filter-btn" onclick="setFilter('great', this)">Great</button>
  <button class="filter-btn" onclick="setFilter('good', this)">Good</button>
  <button class="filter-btn" onclick="setFilter('okay', this)">Okay</button>
  <button class="filter-btn" onclick="setFilter('mixed', this)">Mixed</button>
  <button class="filter-btn" onclick="setFilter('lame', this)">Lame</button>
  <button class="filter-btn" onclick="setFilter('awful', this)">Awful</button>
</div>

<main>
  <p class="game-count" id="game-count"></p>
  <div class="game-list" id="game-list"></div>
</main>

<script>
const GAMES = {games_json};

const RATING_COLORS = {{
  fantastic: '#d4a017',
  great:     '#7c3aed',
  good:      '#2563eb',
  okay:      '#c2620a',
  lame:      '#6b7280',
  awful:     '#16a34a',
  mixed:     '#7c5c3a',
}};

const RATING_LABELS = {{
  fantastic: 'Fantastic',
  great:     'Great',
  good:      'Good',
  okay:      'Okay',
  lame:      'Lame',
  awful:     'Awful',
  mixed:     'Mixed',
}};

const ORDER = ['fantastic','great','good','okay','mixed','lame','awful'];

function escapeHtml(str) {{
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function buildRow(game) {{
  const color = RATING_COLORS[game.rating] || '#888';
  const label = RATING_LABELS[game.rating] || game.rating;
  const slug = game.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');

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

function getInitial(title) {{
  return title.trim()[0]?.toUpperCase() ?? '?';
}}

let currentFilter = 'all';

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

(function init() {{
  document.getElementById('header-meta').textContent =
    `${{GAMES.length}} game${{GAMES.length !== 1 ? 's' : ''}} rated`;
  renderList();
}})();
</script>
</body>
</html>
"""


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'index.html'

    if not os.path.exists(csv_path):
        print(f"Error: '{csv_path}' not found.")
        sys.exit(1)

    print(f"Reading {csv_path}...")
    games = read_csv(csv_path)
    print(f"  Found {len(games)} game(s).")

    covers = asyncio.run(fetch_all_covers(games))

    print(f"Generating {out_path}...")
    html = generate_html(games, covers)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Done → {out_path}")
    print()
    print("Tips:")
    print("  • Re-run any time you update games.csv to refresh the page.")
    print("  • Drop manual covers in a covers/ folder as <slug>.jpg to override")
    print("    Backloggd lookups (e.g. 'hollow-knight.jpg').")
    print("  • If a cover shows wrong, check the slug:")
    print("    title → lowercase, non-alphanumeric → hyphens.")


if __name__ == '__main__':
    main()