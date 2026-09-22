// Launcher shell: auth gate + sidebar wiring + rater iframe bridge.
// Web port of assets/launcher.html's script (pywebview → Firestore/GitHub Action).
import { onAuthChanged, loginGoogle, loginEmail, registerEmail, signOut, getIdToken, authErrorMessage } from './auth.js';
import { loadConfig, saveConfig, loadGames, saveGames, saveSections, watchStatus } from './store.js';

const $ = (id) => document.getElementById(id);

// ── Views ──────────────────────────────────────────────────────────────
const loginView = $('login-view');
const appView   = $('app');

// ── Auth state ─────────────────────────────────────────────────────────
let uid = null;
let statusUnsub = null;

onAuthChanged((user) => {
  if (statusUnsub) { statusUnsub(); statusUnsub = null; }
  if (user) {
    uid = user.uid;
    $('user-email').textContent = user.email || user.displayName || 'Signed in';
    loginView.style.display = 'none';
    appView.style.display = 'flex';
    startApp();
  } else {
    uid = null;
    loginView.style.display = 'flex';
    appView.style.display = 'none';
  }
});

// ── Login UI ───────────────────────────────────────────────────────────
let registerMode = false;
const loginError = $('login-error');

function showLoginError(msg) { loginError.textContent = msg || ''; }

$('login-google').addEventListener('click', async () => {
  showLoginError('');
  try { await loginGoogle(); }
  catch (e) { showLoginError(authErrorMessage(e)); }
});

$('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  showLoginError('');
  const email = $('login-email').value.trim();
  const pw = $('login-password').value;
  try {
    if (registerMode) await registerEmail(email, pw);
    else await loginEmail(email, pw);
  } catch (err) {
    showLoginError(authErrorMessage(err));
  }
});

$('login-toggle-link').addEventListener('click', () => {
  registerMode = !registerMode;
  $('login-submit').textContent = registerMode ? 'Create account' : 'Sign in';
  $('login-toggle-text').textContent = registerMode ? 'Already have an account?' : "Don't have an account?";
  $('login-toggle-link').textContent = registerMode ? 'Sign in' : 'Create one';
  showLoginError('');
});

$('signout-btn').addEventListener('click', () => signOut());

// ── Collapsible sections ───────────────────────────────────────────────
let sectionStates = {};

function applySectionStates(saved) {
  ['urls', 'add_games'].forEach(key => {
    const el = $(key === 'urls' ? 'urls-section' : 'add-games-section');
    if (!el) return;
    const expanded = saved[key] !== false; // default expanded
    el.classList.toggle('collapsed', !expanded);
    sectionStates[key] = expanded;
  });
}

document.querySelectorAll('.section-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.section;
    const section = btn.closest('section');
    const nowCollapsed = section.classList.toggle('collapsed');
    sectionStates[key] = !nowCollapsed;
    if (uid) saveSections(uid, sectionStates).catch(() => {});
  });
});

// ── Save status ────────────────────────────────────────────────────────
let saveStatusTimer = null;
function setSaveStatus(state, msg) {
  const el = $('save-status');
  if (!el) return;
  if (saveStatusTimer) { clearTimeout(saveStatusTimer); saveStatusTimer = null; }
  if (state === 'saving') {
    el.textContent = 'Saving…';
    el.className = 'save-status';
  } else if (state === 'saved') {
    el.textContent = 'Saved.';
    el.className = 'save-status';
    saveStatusTimer = setTimeout(() => { el.textContent = ''; }, 2000);
  } else if (state === 'error') {
    el.textContent = `Save error: ${msg || 'unknown'}`;
    el.className = 'save-status error';
  } else {
    el.textContent = '';
    el.className = 'save-status';
  }
}

function makeSaveCb() {
  return async (games) => {
    if (!uid) return false;
    setSaveStatus('saving');
    try {
      // JSON round-trip produces plain arrays/objects — cross-frame arrays have
      // a foreign Array constructor that Firestore's serializer rejects.
      await saveGames(uid, JSON.parse(JSON.stringify(games)));
      setSaveStatus('saved');
      return true;
    }
    catch (e) { setSaveStatus('error', e.message || String(e)); return false; }
  };
}

// ── Rater iframe bridge ────────────────────────────────────────────────
const raterFrame = $('rater-frame');
let frameReady = false;
let latestGames = null;

function raterBridge() {
  try { return raterFrame.contentWindow.raterBridge || null; } catch (e) { return null; }
}

// Robust handshake: the iframe may finish loading before OR after this module
// runs, so treat it as ready via any of three paths (its ready callback, the
// iframe load event, or an immediate check) — whichever happens first.
function markFrameReady() {
  if (frameReady) return;
  let fn;
  try { fn = raterFrame.contentWindow && raterFrame.contentWindow.initRater; } catch (e) { fn = null; }
  if (typeof fn !== 'function') return;   // not actually ready yet
  frameReady = true;
  maybeInitRater();
}
window.onRaterFrameReady = markFrameReady;
raterFrame.addEventListener('load', markFrameReady);
markFrameReady();  // in case the iframe already loaded

function maybeInitRater() {
  if (!frameReady || latestGames === null) return;
  const fn = raterFrame.contentWindow.initRater;
  if (typeof fn !== 'function') return;
  fn(latestGames, makeSaveCb());
  onRaterLoad();
}

// ── App startup (per sign-in) ──────────────────────────────────────────
async function startApp() {
  const config = await loadConfig(uid);
  $('folder-url').value = config.folder_url || '';
  $('master-url').value = config.master_url || '';
  applySectionStates(config.sections || {});
  setButtonsEnabled(true);

  latestGames = await loadGames(uid);
  maybeInitRater();

  statusUnsub = watchStatus(uid, onStatus);
}

async function reloadGames() {
  latestGames = await loadGames(uid);
  const fn = raterFrame.contentWindow.initRater;
  if (frameReady && typeof fn === 'function') {
    fn(latestGames, makeSaveCb());
    onRaterLoad();
  }
}

// ── URL autosave (debounced) ───────────────────────────────────────────
let urlsSaveTimer = null;
function scheduleSaveUrls() {
  if (urlsSaveTimer) clearTimeout(urlsSaveTimer);
  urlsSaveTimer = setTimeout(async () => {
    const msg = $('save-urls-msg');
    try {
      await saveConfig(uid, $('folder-url').value.trim(), $('master-url').value.trim());
      msg.textContent = 'Saved.';
    } catch (e) {
      msg.textContent = `Error: ${e.message || e}`;
    }
    setTimeout(() => { msg.textContent = ''; }, 2000);
  }, 600);
}
['folder-url', 'master-url'].forEach(id => $(id).addEventListener('input', scheduleSaveUrls));

// ── Add Games (trigger scrape via /api/refresh) ────────────────────────
const opButtons = {
  current_year:     $('btn-current-year'),
  all_played_lists: $('btn-all-lists'),
  historic:         $('btn-historic'),
};
const opLabels = {
  current_year:     'Current Year',
  all_played_lists: 'All Year Lists',
  historic:         'All Games Played',
};

const statusBox        = $('status-box');
const resultBanner     = $('result-banner');
const runningIndicator = $('running-indicator');
const runningOpLabel   = $('running-op-label');

let awaitingScrape = false;  // true from click until we see a fresh done status

function setButtonsEnabled(enabled) {
  Object.values(opButtons).forEach(btn => btn.disabled = !enabled);
}
function renderLog(lines) {
  statusBox.textContent = (lines || []).join('\n');
  statusBox.classList.add('visible');
  statusBox.scrollTop = statusBox.scrollHeight;
}
function showBanner(kind, text) {
  resultBanner.textContent = text;
  resultBanner.className = `banner visible ${kind}`;
}
function showRunning(op) {
  runningOpLabel.textContent = `Running: ${opLabels[op] || op}…`;
  runningIndicator.classList.add('visible');
}
function hideRunning() { runningIndicator.classList.remove('visible'); }

Object.entries(opButtons).forEach(([op, btn]) => {
  btn.addEventListener('click', () => startOp(op));
});

async function startOp(op) {
  resultBanner.className = 'banner';
  statusBox.classList.remove('visible');
  statusBox.textContent = '';
  setButtonsEnabled(false);
  showRunning(op);
  awaitingScrape = true;
  try {
    const token = await getIdToken();
    const resp = await fetch('/api/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ mode: op }),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      throw new Error(`${resp.status} ${text}`.trim());
    }
    renderLog(['Queued — the scraper is starting on GitHub Actions…']);
  } catch (e) {
    awaitingScrape = false;
    hideRunning();
    setButtonsEnabled(true);
    showBanner('error', `Could not start: ${e.message || e}`);
  }
}

// Status doc updates (written live by the GitHub Action scraper).
function onStatus(status) {
  if (!status) return;
  if (status.running) {
    awaitingScrape = true;
    setButtonsEnabled(false);
    showRunning(status.op);
  }
  if (status.log) renderLog(status.log);
  if (status.done && awaitingScrape) {
    awaitingScrape = false;
    hideRunning();
    setButtonsEnabled(true);
    if (status.error) {
      showBanner('error', `Error: ${status.error}`);
    } else {
      const added = status.added || 0;
      showBanner('success',
        `✓ Done — ${added} new game${added === 1 ? '' : 's'} added` +
        (status.covers_found != null ? `, ${status.covers_found} cover(s) ready` : '') + '.');
      reloadGames();
    }
  }
}

// ── Rater controls (view toggle + year list drive the iframe) ──────────
function syncRaterControls(meta) {
  if (!meta) return;
  document.querySelectorAll('.year-item').forEach(b =>
    b.classList.toggle('active', parseInt(b.dataset.year) === meta.currentYear));
  document.querySelectorAll('#view-toggle .view-btn').forEach(b => {
    const v = b.dataset.view;
    b.classList.toggle('active', v === meta.currentView);
    if (v === 'tier' || v === 'list') b.style.display = meta.restricted ? 'none' : '';
  });
}

function buildYearList(meta) {
  const container = $('year-list');
  container.innerHTML = '';
  (meta.years || []).forEach(yr => {
    const btn = document.createElement('button');
    btn.className = 'year-item' + (yr === meta.currentYear ? ' active' : '');
    btn.textContent = String(yr);
    btn.dataset.year = yr;
    btn.addEventListener('click', () => {
      const b = raterBridge();
      if (b) syncRaterControls(b.setYear(yr));
    });
    container.appendChild(btn);
  });
}

function onRaterLoad() {
  const b = raterBridge();
  if (!b) return;
  const meta = b.getMeta();
  buildYearList(meta);
  syncRaterControls(meta);
}

document.querySelectorAll('#view-toggle .view-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const b = raterBridge();
    if (b) syncRaterControls(b.setView(btn.dataset.view));
  });
});

// ── Export Image (current view → PNG download) ─────────────────────────
const exportBtn = $('export-btn');
const exportMsg = $('export-msg');
function setExportMsg(text, isError) {
  exportMsg.textContent = text;
  exportMsg.classList.toggle('error', !!isError);
}

exportBtn.addEventListener('click', async () => {
  const bridge = raterBridge();
  if (!bridge || typeof bridge.exportImage !== 'function') {
    setExportMsg('Rater not ready yet.', true);
    return;
  }
  const meta = bridge.getMeta();
  if (meta.currentView !== 'tier' && meta.currentView !== 'goty') {
    setExportMsg('Switch to Tier or GOTY view to export.', true);
    return;
  }
  exportBtn.disabled = true;
  setExportMsg('Rendering image…', false);
  try {
    const img = await bridge.exportImage();
    if (!img || !img.ok) {
      const reason = img && img.error === 'unsupported-view'
        ? 'Switch to Tier or GOTY view to export.'
        : `Could not create image${img && img.error ? `: ${img.error}` : ''}.`;
      setExportMsg(reason, true);
      return;
    }
    const kind = img.view === 'goty' ? 'GOTY' : 'Tiers';
    const yearStr = String(img.year || 'export').replace(/[^0-9A-Za-z]/g, '') || 'export';
    const a = document.createElement('a');
    a.href = img.dataUrl;
    a.download = `GameRater_${kind}_${yearStr}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setExportMsg(`Saved ${a.download}.`, false);
  } catch (e) {
    setExportMsg(`Export failed: ${e.message || e}`, true);
  } finally {
    exportBtn.disabled = false;
  }
});
