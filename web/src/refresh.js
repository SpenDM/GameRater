// POST /api/refresh   { mode: 'current_year' | 'all_played_lists' | 'historic' }
// Header: Authorization: Bearer <Firebase ID token>
//
// Verifies the caller's Firebase ID token, then triggers the GitHub Actions
// scraper (workflow_dispatch) for that user's uid + mode. The Action reads the
// user's Backloggd URLs from Firestore, scrapes, and writes results back.
import { importX509, jwtVerify } from 'jose';

const VALID_MODES = new Set(['current_year', 'all_played_lists', 'historic']);
const CERTS_URL =
  'https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com';

// Per-isolate cache of Google's Firebase signing certs (PEM by kid).
let _certs = null;
let _certsExp = 0;

async function getCerts() {
  const now = Date.now();
  if (_certs && now < _certsExp) return _certs;
  const resp = await fetch(CERTS_URL);
  if (!resp.ok) throw new Error('could not fetch Firebase certs');
  _certs = await resp.json();
  // Respect Cache-Control max-age; fall back to 1h.
  const cc = resp.headers.get('Cache-Control') || '';
  const m = cc.match(/max-age=(\d+)/);
  _certsExp = now + (m ? parseInt(m[1], 10) : 3600) * 1000;
  return _certs;
}

async function verifyIdToken(token, projectId) {
  const { kid } = JSON.parse(atob(token.split('.')[0].replace(/-/g, '+').replace(/_/g, '/')));
  const certs = await getCerts();
  const pem = certs[kid];
  if (!pem) throw new Error('unknown token key id');
  const key = await importX509(pem, 'RS256');
  const { payload } = await jwtVerify(token, key, {
    issuer: `https://securetoken.google.com/${projectId}`,
    audience: projectId,
  });
  if (!payload.sub) throw new Error('token missing subject');
  return payload; // payload.sub === uid
}

export async function handleRefresh(request, env) {
  const projectId = env.FIREBASE_PROJECT_ID;
  const repo = env.GITHUB_REPO;               // "owner/name"
  const token = env.GITHUB_TOKEN;
  const ref = env.GITHUB_REF || 'main';
  const workflow = env.WORKFLOW_FILE || 'scrape.yml';

  if (!projectId || !repo || !token) {
    return json({ error: 'server not configured' }, 500);
  }

  // 1. Authenticate the caller.
  const authz = request.headers.get('Authorization') || '';
  const idToken = authz.startsWith('Bearer ') ? authz.slice(7) : '';
  if (!idToken) return json({ error: 'missing bearer token' }, 401);

  let uid;
  try {
    const payload = await verifyIdToken(idToken, projectId);
    uid = payload.sub;
  } catch (e) {
    return json({ error: `invalid token: ${e.message || e}` }, 401);
  }

  // 2. Validate mode.
  let mode;
  try {
    ({ mode } = await request.json());
  } catch {
    return json({ error: 'invalid JSON body' }, 400);
  }
  if (!VALID_MODES.has(mode)) return json({ error: 'invalid mode' }, 400);

  // 3. Trigger the workflow for this user.
  const ghResp = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'GameRater-Worker',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref, inputs: { uid, mode } }),
    }
  );

  if (ghResp.status !== 204) {
    const detail = await ghResp.text().catch(() => '');
    return json({ error: `could not trigger scrape (${ghResp.status})`, detail }, 502);
  }

  return json({ ok: true, queued: true }, 202);
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
