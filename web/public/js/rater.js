// GameRater rater view — data-driven web port.
// Ported verbatim from create_game_log_all_played_lists.generate_html()'s
// <script>, with desktop seams (pywebview, local save server, baked-in data)
// replaced by a runtime games array + a save callback (Firestore).

const GOTY_CATEGORIES = [
  { key: 'goty',            label: 'Game of the Year' },
  { key: 'puzzle_strategy', label: 'Puzzle/Strategy' },
  { key: 'action',          label: 'Action' },
  { key: 'pickup_n_play',   label: "Pick Up 'n Play" },
  { key: 'novelty',         label: 'Novelty' },
  { key: 'narrative',       label: 'Narrative' },
  { key: 'world',           label: 'World' },
  { key: 'visuals',         label: 'Visuals' },
  { key: 'audio',           label: 'Audio' },
];

const RATING_COLORS = {
  fantastic: '#d4a017',
  great:     '#7c3aed',
  good:      '#2563eb',
  okay:      '#c2620a',
  lame:      '#7c5c3a',
  mixed:     '#6b7280',
  unrated:   '#3a3a4a',
};

const RATING_LABELS = {
  fantastic: 'Fantastic',
  great:     'Great',
  good:      'Good',
  okay:      'Okay',
  lame:      'Lame',
  mixed:     'Mixed',
  unrated:   'Unrated',
};

const ORDER = ['fantastic','great','good','mixed','okay','lame'];
const ALL_RATINGS = [...ORDER, 'unrated'];

// Year-tab computation constants (mirror the Python scraper).
const HISTORIC_START_YEAR = 2024;
const AWARD_ONLY_CUTOFF_YEAR = 1999;

// ── Runtime data (populated by initRater from the user's games array) ──
let YEARS = [];
let GAMES_BY_YEAR = {};
let YEAR_MODES = {};

// Save hook: launcher/store provides a callback(gamesArray) to persist edits.
let onSaveGames = null;

// Derive YEARS / GAMES_BY_YEAR / YEAR_MODES from a flat games array, using the
// same rules as compute_year_tabs() + generate_html() in the Python source.
function deriveData(games) {
  const playedYears = new Set();
  const releaseYears = [];
  games.forEach(g => {
    const yp = String(g.year_played || '').trim();
    if (/^\d+$/.test(yp)) playedYears.add(parseInt(yp, 10));
    const ry = String(g.release_year || '').trim();
    if (/^\d+$/.test(ry)) releaseYears.push(parseInt(ry, 10));
  });

  const historicYears = [];
  if (releaseYears.length) {
    const earliest = Math.min(...releaseYears);
    for (let yr = HISTORIC_START_YEAR; yr >= earliest; yr--) {
      if (!playedYears.has(yr)) historicYears.push(yr);
    }
  }

  const yearSet = new Set([...playedYears, ...historicYears]);
  YEARS = [...yearSet].sort((a, b) => b - a);

  YEAR_MODES = {};
  YEARS.forEach(yr => {
    if (yr > HISTORIC_START_YEAR) YEAR_MODES[yr] = 'full';
    else if (yr <= AWARD_ONLY_CUTOFF_YEAR) YEAR_MODES[yr] = 'goty-award';
    else YEAR_MODES[yr] = 'goty';
  });

  GAMES_BY_YEAR = {};
  YEARS.forEach(yr => { GAMES_BY_YEAR[yr] = []; });
  games.forEach(g => {
    const yp = String(g.year_played || '').trim();
    let yr = /^\d+$/.test(yp) ? parseInt(yp, 10) : null;
    if (yr === null) {
      const ry = String(g.release_year || '').trim();
      yr = /^\d+$/.test(ry) ? parseInt(ry, 10) : null;
    }
    if (yr !== null && GAMES_BY_YEAR[yr]) {
      GAMES_BY_YEAR[yr].push({
        title:        g.title || '',
        rating:       g.rating || 'unrated',
        review:       g.review || '',
        url:          g.url || '',
        year_played:  yp,
        release_year: String(g.release_year || ''),
        cover:        g.cover || '',
        categories:   Array.isArray(g.categories) ? g.categories.slice() : [],
      });
    }
  });
}

// Cover URLs: local seed paths (covers/slug.jpg) are served same-origin as-is;
// remote Backloggd CDN URLs are proxied through /api/cover so html2canvas can
// rasterize them on export without tainting the canvas.
function coverSrc(c) {
  if (!c) return '';
  if (/^https?:\/\//i.test(c)) return '/api/cover?url=' + encodeURIComponent(c);
  return c;
}

// ── Mutable state ─────────────────────────────────────
// ALL_STATE[year][rating] = [{title, cover, review, rating, url}]
let ALL_STATE = {};
let currentYear = null;
let state = null;  // reference into ALL_STATE[currentYear]

function initAllState() {
  YEARS.forEach(yr => {
    ALL_STATE[yr] = {};
    ALL_RATINGS.forEach(r => ALL_STATE[yr][r] = []);
    (GAMES_BY_YEAR[yr] || []).forEach(g => {
      const r = ALL_RATINGS.includes(g.rating) ? g.rating : 'unrated';
      ALL_STATE[yr][r].push({
        title:        g.title,
        cover:        g.cover  || '',
        review:       g.review || '',
        rating:       r,
        url:          g.url    || '',
        release_year: g.release_year || '',
        categories:   Array.isArray(g.categories) ? g.categories.slice() : [],
      });
    });
  });
  state = ALL_STATE[currentYear];
}

// ── Year tabs ─────────────────────────────────────────
const YEAR_TABS_PER_ROW = 12;

function buildYearTabs() {
  const container = document.getElementById('year-tabs');
  container.innerHTML = '';
  let row = null;
  YEARS.forEach((yr, i) => {
    if (i % YEAR_TABS_PER_ROW === 0) {
      row = document.createElement('div');
      row.className = 'year-tabs-row';
      container.appendChild(row);
    }
    const btn = document.createElement('button');
    btn.className = 'year-tab' + (yr === currentYear ? ' active' : '');
    btn.textContent = String(yr);
    btn.dataset.year = yr;
    btn.addEventListener('click', () => setYear(yr));
    row.appendChild(btn);
  });
}

function yearMode(yr) { return YEAR_MODES[yr] || 'full'; }

function applyViewAvailability() {
  const restricted = yearMode(currentYear) !== 'full';
  document.getElementById('btn-tier').style.display = restricted ? 'none' : '';
  document.getElementById('btn-list').style.display = restricted ? 'none' : '';
}

function setYear(yr) {
  currentYear = yr;
  state = ALL_STATE[yr];
  document.querySelectorAll('.year-tab').forEach(b =>
    b.classList.toggle('active', parseInt(b.dataset.year) === yr));
  applyViewAvailability();
  setView(yearMode(yr) !== 'full' ? 'goty' : currentView);
}

// ── Dirty tracking + autosave ─────────────────────────
let dirty = false;
let autosaveTimer = null;

function markDirty() {
  dirty = true;
  if (autosaveTimer) clearTimeout(autosaveTimer);
  // Debounce so a burst of changes (e.g. a drag) saves once it settles.
  autosaveTimer = setTimeout(saveCSV, 500);
}

// ── CSV export (all years) ────────────────────────────
function buildCSV() {
  const rows = [['title', 'rating', 'review', 'url', 'year_played', 'release_year', 'goty_categories']];
  YEARS.forEach(yr => {
    const yrState = ALL_STATE[yr];
    ALL_RATINGS.forEach(r => {
      (yrState[r] || []).forEach(g => {
        const esc = s => {
          s = s || '';
          return s.includes(',') || s.includes('"') || s.includes('\n')
            ? `"${s.replace(/"/g, '""')}"` : s;
        };
        rows.push([esc(g.title), r, esc(g.review), esc(g.url), String(yr),
                   esc(g.release_year), esc((g.categories || []).join(';'))]);
      });
    });
  });
  return rows.map(r => r.join(',')).join('\n');
}


// Build a flat games array across all years (source of truth for persistence).
function buildGamesArray() {
  const out = [];
  YEARS.forEach(yr => {
    const yrState = ALL_STATE[yr];
    ALL_RATINGS.forEach(r => {
      (yrState[r] || []).forEach(g => {
        out.push({
          title:        g.title || '',
          rating:       r,
          review:       g.review || '',
          url:          g.url || '',
          year_played:  String(yr),
          release_year: g.release_year || '',
          cover:        g.cover || '',
          categories:   (g.categories || []).slice(),
        });
      });
    });
  });
  return out;
}

async function saveCSV() {
  if (typeof onSaveGames !== 'function') { dirty = false; return; }
  try {
    const ok = await onSaveGames(buildGamesArray());
    if (ok !== false) dirty = false;
  } catch (e) { /* keep dirty; will retry on next edit */ }
}


// ── Drag state ────────────────────────────────────────
let dragGame = null;
let dragEl   = null;

// ── Rating picker state ───────────────────────────────
let activePicker      = null;
let activePickerAnchor = null;

function closePicker() {
  if (activePicker) { activePicker.remove(); activePicker = null; activePickerAnchor = null; }
}

// Close picker on any outside click or scroll.
document.addEventListener('click',  e => { if (activePicker && !activePicker.contains(e.target)) closePicker(); });
document.addEventListener('scroll', () => closePicker(), true);

function showRatingPicker(game, anchorEl) {
  closePicker();
  const rect = anchorEl.getBoundingClientRect();
  const picker = document.createElement('div');
  picker.className = 'rating-picker';
  // position: fixed so it escapes any overflow:hidden ancestor (e.g. .tier-view)
  picker.style.left = Math.round(rect.left + rect.width / 2) + 'px';
  picker.style.top  = Math.round(rect.top - 8) + 'px';
  picker.addEventListener('click', e => e.stopPropagation());

  ORDER.forEach(r => {
    const btn = document.createElement('button');
    btn.className = 'rating-picker-btn' + (r === game.rating ? ' active' : '');
    btn.title = RATING_LABELS[r];
    btn.type  = 'button';
    const img = document.createElement('img');
    img.src = `assets/images/${r}.png`;
    img.alt = RATING_LABELS[r];
    img.draggable = false;
    btn.appendChild(img);

    btn.addEventListener('click', e => {
      e.stopPropagation();
      if (r !== game.rating) {
        for (const yr of YEARS) {
          const src = ALL_STATE[yr][game.rating];
          if (!src) continue;
          const idx = src.findIndex(g => g === game);
          if (idx !== -1) {
            src.splice(idx, 1);
            game.rating = r;
            ALL_STATE[yr][r].push(game);
            markDirty();
            break;
          }
        }
      }
      const view = currentView;
      closePicker();
      if (view === 'tier') renderTiers();
      else if (view === 'goty') renderGoty();
      else renderList();
    });

    picker.appendChild(btn);
  });

  document.body.appendChild(picker);
  activePicker = picker;
  activePickerAnchor = anchorEl;
}

let autoScrollRAF = null;

function startAutoScroll(clientY) {
  const ZONE = 80, SPEED = 12;
  cancelAutoScroll();
  function tick() {
    const vh = window.innerHeight;
    if (clientY < ZONE) {
      window.scrollBy(0, -SPEED * (1 - clientY / ZONE));
    } else if (clientY > vh - ZONE) {
      window.scrollBy(0, SPEED * (1 - (vh - clientY) / ZONE));
    }
    autoScrollRAF = requestAnimationFrame(tick);
  }
  autoScrollRAF = requestAnimationFrame(tick);
}

function cancelAutoScroll() {
  if (autoScrollRAF) { cancelAnimationFrame(autoScrollRAF); autoScrollRAF = null; }
}

document.addEventListener('dragover', e => { if (dragGame) startAutoScroll(e.clientY); });
document.addEventListener('dragend',  () => cancelAutoScroll());

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function getInitial(title) {
  return title.trim()[0]?.toUpperCase() ?? '?';
}


function openExternal(url) {
  if (!url) return;
  window.open(url, '_blank', 'noopener');
}


// ── List view ─────────────────────────────────────────
function buildRow(game) {
  const color = RATING_COLORS[game.rating] || '#888';
  const label = RATING_LABELS[game.rating] || game.rating;

  const coverHtml = game.cover
    ? `<img class="game-cover" src="${escapeHtml(coverSrc(game.cover))}" alt="${escapeHtml(game.title)}"
           onerror="this.outerHTML='<div class=\'cover-placeholder\'>${getInitial(game.title)}</div>'" />`
    : `<div class="cover-placeholder">${getInitial(game.title)}</div>`;

  const reviewHtml = game.review
    ? `<p class="game-review">${escapeHtml(game.review)}</p>`
    : '';

  const row = document.createElement('div');
  row.className = 'game-row' + (game.url ? ' clickable' : '');
  row.dataset.rating = game.rating;
  row.style.setProperty('--row-accent', color);
  if (game.url) row.addEventListener('dblclick', () => openExternal(game.url));
  row.innerHTML = `
    <div class="game-cover-wrap cover-hover">${coverHtml}<span class="cover-hover-title">${escapeHtml(game.title)}</span></div>
    <div class="game-body">
      <div class="game-title">${escapeHtml(game.title)}</div>
      ${reviewHtml}
    </div>
    <div class="game-rating-col">
      <span class="rating-pill">${label}</span>
    </div>
  `;
  return row;
}

// ── Tier view ─────────────────────────────────────────
function makeCoverItem(game, rating) {
  const item = document.createElement('div');
  item.className = 'tier-cover-item cover-hover';
  item.draggable = true;
  item.dataset.title  = game.title;
  item.dataset.rating = rating;

  const tooltip = document.createElement('span');
  tooltip.className   = 'cover-hover-title';
  tooltip.textContent = game.title;

  const coverEl = game.cover
    ? (() => {
        const i = document.createElement('img');
        i.src      = coverSrc(game.cover);
        i.alt      = game.title;
        i.draggable = false;
        i.onerror  = function() {
          this.outerHTML = `<div class="tier-cover-placeholder">${getInitial(game.title)}</div>`;
        };
        return i;
      })()
    : (() => {
        const d = document.createElement('div');
        d.className   = 'tier-cover-placeholder';
        d.textContent = getInitial(game.title);
        return d;
      })();

  item.appendChild(tooltip);
  item.appendChild(coverEl);

  let wasDragged = false;
  let clickTimer  = null;
  item.addEventListener('dragstart', e => {
    wasDragged = true;
    dragGame = { title: game.title, fromRating: rating };
    dragEl   = item;
    setTimeout(() => item.classList.add('dragging'), 0);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', game.title);
  });
  item.addEventListener('click', e => {
    if (wasDragged) { wasDragged = false; return; }
    if (activePickerAnchor === item) return;
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    clickTimer = setTimeout(() => { clickTimer = null; showRatingPicker(game, item); }, 220);
  });
  item.addEventListener('dblclick', () => {
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    if (game.url) openExternal(game.url);
  });
  item.addEventListener('dragend', () => {
    item.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    document.querySelectorAll('.drop-before').forEach(el => el.classList.remove('drop-before'));
    cancelAutoScroll();
    dragGame = null;
    dragEl   = null;
  });

  item.addEventListener('dragover', e => {
    if (!dragGame) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.drop-before').forEach(el => el.classList.remove('drop-before'));
    const rect = item.getBoundingClientRect();
    if (e.clientX < rect.left + rect.width / 2) item.classList.add('drop-before');
  });
  item.addEventListener('dragleave', () => item.classList.remove('drop-before'));
  item.addEventListener('drop', e => {
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
  });

  return item;
}

function buildTierRow(rating) {
  const color = RATING_COLORS[rating] || '#888';
  const label = RATING_LABELS[rating] || rating;
  const games = state[rating] || [];

  const row = document.createElement('div');
  row.className = 'tier-row';
  row.dataset.tierRating = rating;
  row.style.setProperty('--tier-color', color);

  const labelCol = document.createElement('div');
  labelCol.className = 'tier-label-col';
  if (rating === 'unrated') {
    const span = document.createElement('span');
    span.className   = 'tier-rating-pill';
    span.textContent = label;
    labelCol.appendChild(span);
  } else {
    const img = document.createElement('img');
    img.className = 'tier-rating-img';
    img.src = `assets/images/${rating}.png`;
    img.alt = label;
    img.onerror = function() {
      this.outerHTML = `<span class="tier-rating-pill">${label}</span>`;
    };
    labelCol.appendChild(img);
  }
  row.appendChild(labelCol);

  const coversDiv = document.createElement('div');
  coversDiv.className = 'tier-covers';
  coversDiv.dataset.dropRating = rating;

  if (games.length === 0) {
    const empty = document.createElement('span');
    empty.className   = 'tier-empty';
    empty.textContent = 'None';
    coversDiv.appendChild(empty);
  } else {
    games.forEach(game => coversDiv.appendChild(makeCoverItem(game, rating)));
  }

  coversDiv.addEventListener('dragover', e => {
    if (!dragGame) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    coversDiv.classList.add('drag-over');
  });
  coversDiv.addEventListener('dragleave', e => {
    if (!coversDiv.contains(e.relatedTarget)) coversDiv.classList.remove('drag-over');
  });
  coversDiv.addEventListener('drop', e => {
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
  });

  row.appendChild(coversDiv);
  return row;
}

// ── View & filter state ───────────────────────────────
let currentFilter = 'all';
let currentView   = 'tier';

function setView(view) {
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
}

function setFilter(filter, btn) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderList();
}

function renderList() {
  const list    = document.getElementById('game-list');
  const countEl = document.getElementById('game-count');
  list.innerHTML = '';
  const allGames = ALL_RATINGS.flatMap(r => state[r]);
  const filtered = currentFilter === 'all'
    ? allGames
    : allGames.filter(g => g.rating === currentFilter);
  if (filtered.length === 0) {
    list.innerHTML = '<div class="empty">No games with this rating yet.</div>';
    countEl.textContent = '';
    return;
  }
  const sorted = [...filtered].sort((a, b) =>
    ALL_RATINGS.indexOf(a.rating) - ALL_RATINGS.indexOf(b.rating));
  countEl.textContent = `${sorted.length} game${sorted.length !== 1 ? 's' : ''}`;
  sorted.forEach(game => list.appendChild(buildRow(game)));
}

function renderTiers() {
  const container = document.getElementById('tier-view');
  container.innerHTML = '';
  ORDER.forEach(rating => container.appendChild(buildTierRow(rating)));
  const divider = document.createElement('div');
  divider.style.cssText = 'height:1px; background:var(--border); margin:8px 0;';
  container.appendChild(divider);
  container.appendChild(buildTierRow('unrated'));
  const total = ALL_RATINGS.reduce((n, r) => n + (state[r] || []).length, 0);
  document.getElementById('game-count').textContent =
    `${total} game${total !== 1 ? 's' : ''}`;
}

// ── GOTY view ─────────────────────────────────────────
let gotyDragGame = null;

document.addEventListener('dragover', e => { if (gotyDragGame) startAutoScroll(e.clientY); });
document.addEventListener('dragend',  () => { if (gotyDragGame) cancelAutoScroll(); });

function allGamesFlat() {
  return YEARS.flatMap(yr => ALL_RATINGS.flatMap(r => ALL_STATE[yr][r] || []));
}

function findGameByTitle(title) {
  return allGamesFlat().find(g => g.title === title) || null;
}

function findCategoryHolder(key, year) {
  return allGamesFlat().find(g =>
    parseInt(g.release_year, 10) === year && (g.categories || []).includes(key)) || null;
}

function assignCategory(key, title) {
  const game = findGameByTitle(title);
  if (!game) return;
  const holder = findCategoryHolder(key, currentYear);
  if (holder && holder.title !== game.title) {
    holder.categories = holder.categories.filter(c => c !== key);
  }
  if (!game.categories.includes(key)) game.categories.push(key);
  markDirty();
  renderGoty();
}

function moveCategory(key, fromCategory, title) {
  if (key === fromCategory) return;
  const game = findGameByTitle(title);
  if (!game) return;
  game.categories = game.categories.filter(c => c !== fromCategory);
  const holder = findCategoryHolder(key, currentYear);
  if (holder && holder.title !== game.title) {
    holder.categories = holder.categories.filter(c => c !== key);
  }
  if (!game.categories.includes(key)) game.categories.push(key);
  markDirty();
  renderGoty();
}

function removeCategory(key, title) {
  const game = findGameByTitle(title);
  if (!game) return;
  game.categories = game.categories.filter(c => c !== key);
  markDirty();
  renderGoty();
}

function buildGotySlot(cat, large) {
  const slot = document.createElement('div');
  slot.className = 'goty-slot' + (large ? ' goty-slot-goty' : '');

  const artWrap = document.createElement('div');
  artWrap.className = 'goty-slot-art';

  const holder = findCategoryHolder(cat.key, currentYear);

  const artBox = document.createElement('div');
  artBox.className = 'goty-slot-cover-box';

  if (holder) {
    artBox.classList.add('cover-hover');
    let wasDragged = false;
    const img = holder.cover
      ? (() => {
          const i = document.createElement('img');
          i.className = 'goty-slot-cover';
          i.src = coverSrc(holder.cover);
          i.alt = holder.title;
          i.draggable = false;
          i.onerror = function() {
            this.outerHTML = `<div class="goty-slot-cover goty-slot-placeholder">${getInitial(holder.title)}</div>`;
          };
          return i;
        })()
      : (() => {
          const d = document.createElement('div');
          d.className = 'goty-slot-cover goty-slot-placeholder';
          d.textContent = getInitial(holder.title);
          return d;
        })();
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
    removeBtn.addEventListener('click', e => {
      e.stopPropagation();
      removeCategory(cat.key, holder.title);
    });
    artBox.appendChild(removeBtn);

    artBox.addEventListener('dragstart', e => {
      wasDragged = true;
      gotyDragGame = { title: holder.title, mode: 'slot', fromCategory: cat.key };
      setTimeout(() => artBox.classList.add('dragging'), 0);
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', holder.title);
    });
    artBox.addEventListener('dragend', () => {
      artBox.classList.remove('dragging');
      gotyDragGame = null;
    });
    let slotClickTimer = null;
    artBox.addEventListener('click', e => {
      if (wasDragged) { wasDragged = false; return; }
      if (activePickerAnchor === artBox) return;
      if (slotClickTimer) { clearTimeout(slotClickTimer); slotClickTimer = null; }
      slotClickTimer = setTimeout(() => { slotClickTimer = null; showRatingPicker(holder, artBox); }, 220);
    });
    artBox.addEventListener('dblclick', () => {
      if (slotClickTimer) { clearTimeout(slotClickTimer); slotClickTimer = null; }
      if (holder.url) openExternal(holder.url);
    });
  } else {
    artBox.classList.add('goty-slot-empty');
  }

  artWrap.appendChild(artBox);
  slot.appendChild(artWrap);

  const label = document.createElement('div');
  label.className = 'goty-slot-label';
  label.textContent = cat.label;
  slot.appendChild(label);

  slot.addEventListener('dragover', e => {
    if (!gotyDragGame) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    slot.classList.add('drag-over');
  });
  slot.addEventListener('dragleave', e => {
    if (!slot.contains(e.relatedTarget)) slot.classList.remove('drag-over');
  });
  slot.addEventListener('drop', e => {
    e.preventDefault();
    slot.classList.remove('drag-over');
    if (!gotyDragGame) return;
    if (gotyDragGame.mode === 'candidate') assignCategory(cat.key, gotyDragGame.title);
    else if (gotyDragGame.mode === 'slot') moveCategory(cat.key, gotyDragGame.fromCategory, gotyDragGame.title);
    gotyDragGame = null;
  });

  return slot;
}

function buildGotyCandidate(game) {
  const item = document.createElement('div');
  item.className = 'tier-cover-item cover-hover';
  item.draggable = true;

  const tooltip = document.createElement('span');
  tooltip.className   = 'cover-hover-title';
  tooltip.textContent = game.title;

  const coverEl = game.cover
    ? (() => {
        const i = document.createElement('img');
        i.src = coverSrc(game.cover);
        i.alt = game.title;
        i.draggable = false;
        i.onerror = function() {
          this.outerHTML = `<div class="tier-cover-placeholder">${getInitial(game.title)}</div>`;
        };
        return i;
      })()
    : (() => {
        const d = document.createElement('div');
        d.className   = 'tier-cover-placeholder';
        d.textContent = getInitial(game.title);
        return d;
      })();

  item.appendChild(tooltip);
  item.appendChild(coverEl);

  let wasDragged = false;
  let clickTimer  = null;
  item.addEventListener('dragstart', e => {
    wasDragged = true;
    gotyDragGame = { title: game.title, mode: 'candidate' };
    setTimeout(() => item.classList.add('dragging'), 0);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', game.title);
  });
  item.addEventListener('dragend', () => {
    item.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
    cancelAutoScroll();
    gotyDragGame = null;
  });
  item.addEventListener('click', e => {
    if (wasDragged) { wasDragged = false; return; }
    if (activePickerAnchor === item) return;
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    clickTimer = setTimeout(() => { clickTimer = null; showRatingPicker(game, item); }, 220);
  });
  item.addEventListener('dblclick', () => {
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    if (game.url) openExternal(game.url);
  });

  return item;
}

function renderGoty() {
  const container = document.getElementById('goty-view');
  container.innerHTML = '';

  const slotsWrap = document.createElement('div');
  slotsWrap.className = 'goty-slots';

  const gotyCat = GOTY_CATEGORIES[0];
  const gotyRow = document.createElement('div');
  gotyRow.className = 'goty-row-main';
  gotyRow.appendChild(buildGotySlot(gotyCat, true));
  slotsWrap.appendChild(gotyRow);

  if (yearMode(currentYear) !== 'goty-award') {
    const grid = document.createElement('div');
    grid.className = 'goty-grid';
    GOTY_CATEGORIES.slice(1).forEach(cat => grid.appendChild(buildGotySlot(cat, false)));
    slotsWrap.appendChild(grid);
  }

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

  if (candidates.length === 0) {
    const empty = document.createElement('span');
    empty.className   = 'tier-empty';
    empty.textContent = 'No games released in ' + currentYear + ' on this list.';
    candidatesWrap.appendChild(empty);
  } else {
    candidates.forEach(game => candidatesWrap.appendChild(buildGotyCandidate(game)));
  }

  container.appendChild(candidatesWrap);

  document.getElementById('game-count').textContent =
    `${candidates.length} candidate${candidates.length !== 1 ? 's' : ''}`;
}

// ── Export the current view to a PNG (rasterized with html2canvas) ────
// Builds a clean off-screen copy of just the tiers (Tier view, unrated
// excluded) or the award slots (GOTY view, candidates excluded) for the
// current year, then hands the resulting PNG data URL back to the launcher.
async function exportImage() {
  const view = currentView;
  if (view !== 'tier' && view !== 'goty') {
    return { ok: false, error: 'unsupported-view' };
  }
  if (typeof html2canvas !== 'function') {
    return { ok: false, error: 'html2canvas-missing' };
  }

  const refView = document.getElementById(view === 'tier' ? 'tier-view' : 'goty-view');
  const width = Math.max(refView ? refView.offsetWidth : 0, 640);

  const wrap = document.createElement('div');
  wrap.className = 'export-capture';
  wrap.style.width = width + 'px';

  if (view === 'tier') {
    // Rated tiers only — the "unrated" row is intentionally left out.
    const tiers = document.createElement('div');
    tiers.className = 'tier-view';
    ORDER.forEach(rating => tiers.appendChild(buildTierRow(rating)));
    wrap.appendChild(tiers);
  } else {
    // All award slots, without the candidates picker below them.
    const slotsWrap = document.createElement('div');
    slotsWrap.className = 'goty-slots';
    const gotyRow = document.createElement('div');
    gotyRow.className = 'goty-row-main';
    gotyRow.appendChild(buildGotySlot(GOTY_CATEGORIES[0], true));
    slotsWrap.appendChild(gotyRow);
    if (yearMode(currentYear) !== 'goty-award') {
      const grid = document.createElement('div');
      grid.className = 'goty-grid';
      GOTY_CATEGORIES.slice(1).forEach(cat => grid.appendChild(buildGotySlot(cat, false)));
      slotsWrap.appendChild(grid);
    }
    wrap.appendChild(slotsWrap);
  }

  document.body.appendChild(wrap);
  await Promise.all(Array.from(wrap.querySelectorAll('.tier-rating-img')).map(img =>
    img.complete ? Promise.resolve() : new Promise(r => { img.onload = r; img.onerror = r; })
  ));
  wrap.querySelectorAll('.tier-rating-img').forEach(img => {
    if (img.naturalWidth && img.naturalHeight) {
      const scale = Math.min(140 / img.naturalWidth, 140 / img.naturalHeight);
      img.style.width  = Math.round(img.naturalWidth  * scale) + 'px';
      img.style.height = Math.round(img.naturalHeight * scale) + 'px';
    }
  });
  try {
    const bg = getComputedStyle(document.body).backgroundColor || '#0f0f13';
    const canvas = await html2canvas(wrap, {
      backgroundColor: bg,
      scale: 2,
      useCORS: true,
      logging: false,
    });
    return { ok: true, dataUrl: canvas.toDataURL('image/png'), view: view, year: String(currentYear) };
  } catch (e) {
    return { ok: false, error: String(e) };
  } finally {
    wrap.remove();
  }
}

// Bridge so the launcher sidebar (parent frame) can drive year/view selection
// and read the current state. The in-page year tabs / view toggle are hidden;
// these call the same setYear/setView functions that update everything.
window.raterBridge = {
  getMeta: () => ({
    years: YEARS,
    yearModes: YEAR_MODES,
    currentYear: currentYear,
    currentView: currentView,
    restricted: yearMode(currentYear) !== 'full',
  }),
  setYear: (yr) => { setYear(yr); return window.raterBridge.getMeta(); },
  setView: (v) => { setView(v); return window.raterBridge.getMeta(); },
  exportImage: () => exportImage(),
};

// Entry point: (re)initialize the rater with a games array + save callback.
// Called by the launcher after Firestore data loads and after each refresh.
window.initRater = function(games, saveCb) {
  onSaveGames = saveCb || null;
  deriveData(Array.isArray(games) ? games : []);
  ALL_STATE = {};
  currentYear = YEARS[0] || null;
  if (currentYear === null) {
    // No games yet — clear the views.
    document.getElementById('year-tabs').innerHTML = '';
    document.getElementById('tier-view').innerHTML = '';
    document.getElementById('goty-view').innerHTML = '';
    document.getElementById('game-list').innerHTML = '';
    return;
  }
  initAllState();
  buildYearTabs();
  applyViewAvailability();
  setView(yearMode(currentYear) !== 'full' ? 'goty' : 'tier');
};
