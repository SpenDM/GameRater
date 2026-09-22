// GET /api/cover?url=<encoded Backloggd CDN image URL>
//
// Proxies a remote cover image through our own origin so html2canvas can draw
// it onto a canvas during export without tainting it (cross-origin images from
// the Backloggd CDN don't send permissive CORS headers). Results are cached at
// the edge. Only backloggd/igdb image hosts are allowed, to avoid an open proxy.
const ALLOWED_HOSTS = [
  'backloggd.com',
  'images.igdb.com',
  'igdb.com',
];

function hostAllowed(hostname) {
  return ALLOWED_HOSTS.some(h => hostname === h || hostname.endsWith('.' + h));
}

export async function handleCover(request, env, ctx) {
  const reqUrl = new URL(request.url);
  const target = reqUrl.searchParams.get('url');

  if (!target) {
    return new Response('missing url', { status: 400 });
  }

  let parsed;
  try {
    parsed = new URL(target);
  } catch {
    return new Response('invalid url', { status: 400 });
  }
  if (parsed.protocol !== 'https:' || !hostAllowed(parsed.hostname)) {
    return new Response('host not allowed', { status: 403 });
  }

  // Serve from the Cloudflare cache when possible.
  const cache = caches.default;
  const cacheKey = new Request(reqUrl.toString(), request);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const upstream = await fetch(parsed.toString(), {
    headers: { 'User-Agent': 'GameRater/1.0 (+cover-proxy)' },
    cf: { cacheTtl: 86400, cacheEverything: true },
  });
  if (!upstream.ok) {
    return new Response('upstream error', { status: 502 });
  }

  const headers = new Headers();
  headers.set('Content-Type', upstream.headers.get('Content-Type') || 'image/jpeg');
  headers.set('Cache-Control', 'public, max-age=86400, immutable');
  headers.set('Access-Control-Allow-Origin', '*');

  const resp = new Response(upstream.body, { status: 200, headers });
  ctx.waitUntil(cache.put(cacheKey, resp.clone()));
  return resp;
}
