#!/usr/bin/env python3
"""
Game Ratings HTML Generator
Usage: python3 generate.py [input.csv] [output.html]
Defaults: games.csv -> game_log.html
"""

import csv
import json
import sys
import os
from pathlib import Path

VALID_RATINGS = ['fantastic', 'great', 'good', 'okay', 'boring', 'yuck', 'mixed']

RATING_LABELS = {
    'fantastic': 'Fantastic',
    'great': 'Great',
    'good': 'Good',
    'okay': 'Okay',
    'boring': 'Boring',
    'yuck': 'Yuck',
    'mixed': 'Mixed',
}

RATING_COLORS = {
    'fantastic': '#d4a017',
    'great':     '#7c3aed',
    'good':      '#2563eb',
    'okay':      '#c2620a',
    'boring':    '#6b7280',
    'yuck':      '#16a34a',
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


def generate_html(games: list[dict], title: str = "My Game Ratings") -> str:
    games_json = json.dumps(games, ensure_ascii=False)

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

    header h1 span {{
      color: var(--accent);
    }}

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

    .filter-btn:hover {{
      border-color: var(--accent);
      color: var(--text);
    }}

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
      gap: 0;
      background: var(--surface);
      transition: background 0.15s ease;
      position: relative;
    }}

    .game-row:hover {{
      background: var(--surface2);
    }}

    /* Rating stripe */
    .game-row::before {{
      content: '';
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
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
      position: relative;
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
      background: var(--surface2);
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

    .rating-badge {{
      display: flex;
      align-items: center;
      white-space: nowrap;
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
  <h1>My <span>Game Ratings</span></h1>
  <p class="header-meta" id="header-meta">Loading...</p>
</header>

<div class="filter-bar">
  <span class="filter-label">Filter</span>
  <button class="filter-btn active" data-filter="all" onclick="setFilter('all', this)">All</button>
  <button class="filter-btn" data-filter="fantastic" onclick="setFilter('fantastic', this)">Fantastic</button>
  <button class="filter-btn" data-filter="great" onclick="setFilter('great', this)">Great</button>
  <button class="filter-btn" data-filter="good" onclick="setFilter('good', this)">Good</button>
  <button class="filter-btn" data-filter="okay" onclick="setFilter('okay', this)">Okay</button>
  <button class="filter-btn" data-filter="mixed" onclick="setFilter('mixed', this)">Mixed</button>
  <button class="filter-btn" data-filter="boring" onclick="setFilter('boring', this)">Boring</button>
  <button class="filter-btn" data-filter="yuck" onclick="setFilter('yuck', this)">Yuck</button>
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
  boring:    '#6b7280',
  yuck:      '#16a34a',
  mixed:     '#7c5c3a',
}};

const RATING_LABELS = {{
  fantastic: 'Fantastic',
  great:     'Great',
  good:      'Good',
  okay:      'Okay',
  boring:    'Boring',
  yuck:      'Yuck',
  mixed:     'Mixed',
}};

// Cover cache to avoid re-fetching
const coverCache = {{}};

async function fetchCover(title) {{
  if (coverCache[title]) return coverCache[title];

  // 1. Check for local file in covers/ folder
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');
  const localExts = ['jpg', 'jpeg', 'png', 'webp'];
  for (const ext of localExts) {{
    const local = `covers/${{slug}}.${{ext}}`;
    // We'll try this in the img onerror chain instead
  }}

  // 2. Try RAWG.io (free, CORS-friendly)
  try {{
    const q = encodeURIComponent(title);
    const res = await fetch(`https://api.rawg.io/api/games?search=${{q}}&page_size=1`, {{
      headers: {{ 'User-Agent': 'GameRatingsList/1.0' }}
    }});
    if (res.ok) {{
      const data = await res.json();
      if (data.results && data.results[0] && data.results[0].background_image) {{
        coverCache[title] = data.results[0].background_image;
        return coverCache[title];
      }}
    }}
  }} catch (e) {{}}

  // 3. No cover found
  coverCache[title] = null;
  return null;
}}

let currentFilter = 'all';
let renderedRows = {{}};

function getInitial(title) {{
  return title.trim()[0]?.toUpperCase() ?? '?';
}}

function buildRow(game) {{
  const color = RATING_COLORS[game.rating] || '#888';
  const label = RATING_LABELS[game.rating] || game.rating;
  const slug = game.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');

  const reviewHtml = game.review
    ? `<p class="game-review">${{escapeHtml(game.review)}}</p>`
    : '';

  const row = document.createElement('div');
  row.className = 'game-row';
  row.dataset.rating = game.rating;
  row.style.setProperty('--row-accent', color);

  row.innerHTML = `
    <div class="game-cover-wrap">
      <div class="cover-placeholder" id="placeholder-${{slug}}">${{getInitial(game.title)}}</div>
    </div>
    <div class="game-body">
      <div class="game-title">${{escapeHtml(game.title)}}</div>
      ${{reviewHtml}}
    </div>
    <div class="game-rating-col">
      <div class="rating-badge">
        <span class="rating-pill">${{label}}</span>
      </div>
    </div>
  `;

  return {{ row, slug }};
}}

function escapeHtml(str) {{
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

async function loadCover(game, row, slug) {{
  const placeholder = row.querySelector(`#placeholder-${{slug}}`);
  const wrap = row.querySelector('.game-cover-wrap');

  // Try local cover first
  const localSlug = game.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');
  for (const ext of ['jpg', 'jpeg', 'png', 'webp']) {{
    const local = `covers/${{localSlug}}.${{ext}}`;
    const testImg = new Image();
    const localOk = await new Promise(res => {{
      testImg.onload = () => res(true);
      testImg.onerror = () => res(false);
      testImg.src = local;
    }});
    if (localOk) {{
      const img = document.createElement('img');
      img.className = 'game-cover';
      img.src = local;
      img.alt = game.title;
      placeholder.replaceWith(img);
      return;
    }}
  }}

  // Fetch from RAWG
  const coverUrl = await fetchCover(game.title);
  if (coverUrl) {{
    const img = document.createElement('img');
    img.className = 'game-cover';
    img.src = coverUrl;
    img.alt = game.title;
    img.onerror = () => {{ img.replaceWith(placeholder); }};
    placeholder.replaceWith(img);
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

  countEl.textContent = `${{filtered.length}} game${{filtered.length !== 1 ? 's' : ''}}`;

  // Order: fantastic → great → good → okay → mixed → boring → yuck
  const ORDER = ['fantastic','great','good','okay','mixed','boring','yuck'];
  const sorted = [...filtered].sort((a, b) =>
    ORDER.indexOf(a.rating) - ORDER.indexOf(b.rating)
  );

  sorted.forEach(game => {{
    if (!renderedRows[game.title]) {{
      const {{ row, slug }} = buildRow(game);
      renderedRows[game.title] = {{ row, slug }};
      // Kick off cover fetch without blocking render
      loadCover(game, row, slug);
    }}
    list.appendChild(renderedRows[game.title].row);
  }});
}}

// Init
(function init() {{
  const total = GAMES.length;
  document.getElementById('header-meta').textContent =
    `${{total}} game${{total !== 1 ? 's' : ''}} rated`;
  renderList();
}})();
</script>
</body>
</html>
"""


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else 'games.csv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'game_log.html'

    if not os.path.exists(csv_path):
        print(f"Error: '{csv_path}' not found.")
        sys.exit(1)

    print(f"Reading {csv_path}...")
    games = read_csv(csv_path)
    print(f"  Found {len(games)} game(s).")

    html = generate_html(games)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Generated {out_path}")
    print()
    print("Setup notes:")
    print("  • Optionally place game cover images in a 'covers/' folder.")
    print("    Name them by slug, e.g. 'hollow-knight.jpg'. These take priority")
    print("    over auto-fetched covers.")
    print("  • Cover art is auto-fetched from RAWG.io when viewing in a browser.")


if __name__ == '__main__':
    main()