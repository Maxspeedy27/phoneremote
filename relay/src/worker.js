// Kumpas relay: serves the phone page over HTTPS and passes messages
// between a laptop and its phones, so they work on any network with internet.
//
// Each laptop has a room (a Durable Object) named by its room id. The relay
// never sees inside messages: they are end-to-end encrypted with keys from
// pairing, and it doesn't even parse them, it just prefixes the phone's id.
//
//   laptop  wss://<relay>/ws/host/<room>    first message {"t":"auth","secret":...}
//   phone   wss://<relay>/ws/phone/<room>
//   phone  -> relay  {"i":1,"p":"/api/cmd","b":{...}}
//   relay  -> laptop "<phone id> " + that message
//   laptop -> relay  "<phone id> " + {"i":1,"s":200,"b":{...}}
//   relay  -> phone  the reply as is; plus {"t":"host","online":bool} notices
//   "ping" -> "pong" answered without waking the room (hibernation)
import { DurableObject } from 'cloudflare:workers';

const ROOM = '[A-Za-z0-9_-]{22}';
const MAX_PHONES = 8;
const MAX_MESSAGE = 1024 * 1024;
const AUTH_TIMEOUT_MS = 10000;

const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; " +
            "img-src 'self' blob:; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

// URL path -> file in the phone page's folder. Nothing else is served.
const STATIC = {
  '/static/style.css': 'style.css',
  '/static/app.js': 'app.js',
  '/static/crypto.js': 'crypto.js',
  '/static/nacl-fast.min.js': 'vendor/nacl-fast.min.js',
  '/static/icon.svg': 'icon.svg',
  '/static/icon-192.png': 'icon-192.png',
  '/static/icon-512.png': 'icon-512.png',
  '/apple-touch-icon.png': 'icon-180.png',
};

async function asset(env, request, file, cache) {
  const res = await env.ASSETS.fetch(new Request(new URL('/' + file, request.url)));
  if (!res.ok) return new Response('Not found', { status: 404 });
  const out = new Response(res.body, res);
  out.headers.set('Cache-Control', cache);
  out.headers.set('X-Content-Type-Options', 'nosniff');
  out.headers.set('Referrer-Policy', 'no-referrer');
  out.headers.set('Strict-Transport-Security', 'max-age=31536000');
  // Older Safari doesn't count wss:// as 'self', so name this relay's WebSocket address too.
  if (file.endsWith('.html')) {
    const ws = (new URL(request.url).protocol === 'https:' ? 'wss://' : 'ws://') + new URL(request.url).host;
    out.headers.set('Content-Security-Policy', CSP.replace("connect-src 'self'", "connect-src 'self' " + ws));
  }
  if (file.endsWith('.webmanifest')) out.headers.set('Content-Type', 'application/manifest+json');
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    let m;
    if ((m = new RegExp(`^/ws/(host|phone)/(${ROOM})$`).exec(path))) {
      if (request.headers.get('Upgrade') !== 'websocket') return new Response('Expected a WebSocket', { status: 426 });
      return env.ROOMS.get(env.ROOMS.idFromName(m[2])).fetch(request);
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', { status: 405 });
    if (new RegExp(`^/r/${ROOM}$`).test(path)) return Response.redirect(url.origin + path + '/', 301);
    if (path === '/' || new RegExp(`^/r/${ROOM}/$`).test(path)) return asset(env, request, 'index.html', 'no-store');
    if (path === '/manifest.webmanifest' || new RegExp(`^/r/${ROOM}/manifest\\.webmanifest$`).test(path)) {
      return asset(env, request, 'manifest.webmanifest', 'no-cache');
    }
    if (STATIC[path]) return asset(env, request, STATIC[path], 'no-cache');
    if (path === '/favicon.ico') return new Response(null, { status: 204 });
    return new Response('Not found', { status: 404 });
  },
};

async function roomOf(secret) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(secret)));
  let s = '';
  for (const b of digest.slice(0, 16)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export class Room extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    // Keep-alives are answered by the runtime without waking the room.
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
  }

  host() {
    for (const ws of this.ctx.getWebSockets('host')) {
      const a = ws.deserializeAttachment();
      if (a && a.authed) return ws;
    }
    return null;
  }

  tellPhones(message) {
    const text = JSON.stringify(message);
    for (const ws of this.ctx.getWebSockets('phone')) {
      try { ws.send(text); } catch (e) {}
    }
  }

  async fetch(request) {
    const [, , role, room] = new URL(request.url).pathname.split('/');
    const [client, server] = Object.values(new WebSocketPair());
    if (role === 'phone') {
      if (this.ctx.getWebSockets('phone').length >= MAX_PHONES) {
        return new Response('Too many phones connected to this laptop', { status: 429 });
      }
      const id = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
      this.ctx.acceptWebSocket(server, ['phone', 'p:' + id]);
      server.serializeAttachment({ role: 'phone', id });
      server.send(JSON.stringify({ t: 'host', online: this.host() !== null }));
    } else {
      this.ctx.acceptWebSocket(server, ['host']);
      server.serializeAttachment({ role: 'host', room, authed: false, since: Date.now() });
      await this.ctx.storage.setAlarm(Date.now() + AUTH_TIMEOUT_MS);
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws, message) {
    if (typeof message !== 'string' || message.length > MAX_MESSAGE) return;
    const a = ws.deserializeAttachment() || {};
    if (a.role === 'phone') {
      const host = this.host();
      if (host) {
        host.send(a.id + ' ' + message);
      } else {
        let i = null;
        try { i = JSON.parse(message).i; } catch (e) {}
        ws.send(JSON.stringify({ i, s: 503, b: { ok: false, code: 'offline',
          error: "The laptop isn't connected. Open Kumpas on the laptop and check it has internet." } }));
      }
      return;
    }
    if (!a.authed) {
      let msg = null;
      try { msg = JSON.parse(message); } catch (e) {}
      if (!msg || msg.t !== 'auth' || typeof msg.secret !== 'string' || await roomOf(msg.secret) !== a.room) {
        ws.send(JSON.stringify({ t: 'error', error: 'This laptop is not allowed in this room.' }));
        ws.close(1008, 'wrong secret');
        return;
      }
      for (const other of this.ctx.getWebSockets('host')) {   // a laptop that reconnects replaces its old connection
        const oa = other.deserializeAttachment();
        if (other !== ws && oa && oa.authed) { try { other.close(4000, 'replaced'); } catch (e) {} }
      }
      ws.serializeAttachment({ ...a, authed: true });
      ws.send(JSON.stringify({ t: 'ready' }));
      this.tellPhones({ t: 'host', online: true });
      return;
    }
    const space = message.indexOf(' ');
    if (space < 1) return;
    const phone = this.ctx.getWebSockets('p:' + message.slice(0, space))[0];
    if (phone) { try { phone.send(message.slice(space + 1)); } catch (e) {} }
  }

  async webSocketClose(ws, code, reason) {
    const a = ws.deserializeAttachment() || {};
    try { ws.close(code === 1005 ? 1000 : code, reason); } catch (e) {}
    if (a.role === 'host' && a.authed && !this.ctx.getWebSockets('host').some(o => o !== ws && (o.deserializeAttachment() || {}).authed)) {
      this.tellPhones({ t: 'host', online: false });
    }
  }

  async webSocketError(ws) {
    await this.webSocketClose(ws, 1011, 'error');
  }

  async alarm() {
    // Laptops that never proved they own the room are disconnected.
    for (const ws of this.ctx.getWebSockets('host')) {
      const a = ws.deserializeAttachment() || {};
      if (!a.authed && Date.now() - a.since >= AUTH_TIMEOUT_MS - 50) { try { ws.close(1008, 'no auth'); } catch (e) {} }
    }
  }
}
