// Worker entrypoint: routes /api/* to the handlers, everything else falls
// through to the static assets binding (web/public). With static assets
// configured, requests matching a file are served directly and never reach this
// Worker; only /api/* and unmatched paths get here.
import { handleRefresh } from './refresh.js';
import { handleCover } from './cover.js';

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/api/refresh') {
      if (request.method !== 'POST') return new Response('method not allowed', { status: 405 });
      return handleRefresh(request, env);
    }

    if (url.pathname === '/api/cover') {
      if (request.method !== 'GET') return new Response('method not allowed', { status: 405 });
      return handleCover(request, env, ctx);
    }

    // Static assets (index.html, rater.html, js/, css, covers, images).
    return env.ASSETS.fetch(request);
  },
};
