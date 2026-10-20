(() => {
'use strict';
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const { b64d, seal, unseal, pairingCode, keyLength } = window.RemoteCrypto;

const SEND_INTERVAL_MS = 16;   // ~60 batched updates per second
const ACCEL = 0.05;            // extra gain per px moved in one touch event
const SCROLL_GAIN = 1.5;
const TAP_MAX_MS = 250, TAP_SLOP_PX = 10;
const DOUBLE_TAP_MS = 350, DOUBLE_TAP_SLOP_PX = 30;
const PAIR_TIMEOUT_MS = 75000; // the laptop user gets 60 s to approve

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem('phoneRemote.' + key); return v === null ? fallback : JSON.parse(v); }
    catch (e) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem('phoneRemote.' + key, JSON.stringify(value)); } catch (e) {}
  },
};

const statusEl = $('#status');
function setStatus(msg, isError) {
  statusEl.textContent = msg;
  statusEl.classList.toggle('err', !!isError);
}
function buzz(ms) {
  try { if (navigator.vibrate) navigator.vibrate(ms || 12); } catch (e) {}
}

// ---------- Pairing overlay ----------
const overlay = $('#overlay'), retryBtn = $('#overlay-retry');
function showOverlay(title, text, code, canRetry) {
  $('#overlay-title').textContent = title;
  $('#overlay-text').textContent = text || '';
  $('#overlay-code').textContent = code ? code.slice(0, 3) + ' ' + code.slice(3) : '';
  retryBtn.hidden = !canRetry;
  overlay.classList.add('show');
}
function hideOverlay() { overlay.classList.remove('show'); }
retryBtn.addEventListener('click', () => { buzz(); connect(); });

// ---------- HTTP ----------
class ApiError extends Error {
  constructor(message, code) { super(message); this.code = code; }
}

async function request(path, body, timeoutMs) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(path, {
      method: 'POST', cache: 'no-store', signal: ctl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) throw new ApiError(data.error || 'Laptop error ' + r.status, data.code);
    return data;
  } catch (e) {
    if (e.name === 'AbortError') throw new ApiError('Timed out - laptop not responding', 'network');
    if (e instanceof TypeError) throw new ApiError('Cannot reach laptop - same Wi-Fi? Phone Remote running?', 'network');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// ---------- Pairing and sessions ----------
// device: {id, key, host} issued by the laptop when pairing was approved.
let device = store.get('device', null);
let deviceKey = null;
try { if (device) deviceKey = b64d(device.key); } catch (e) { device = null; }
let pairingKey = null;   // one-time key from the QR code's #k=...
let session = null, seq = 0;
let connecting = null;

function takePairingKeyFromUrl() {
  if (!location.hash) return;
  const k = new URLSearchParams(location.hash.slice(1)).get('k');
  // Drop the key from the address bar and history; it is single-use anyway.
  history.replaceState(null, '', location.pathname + location.search);
  try {
    const key = k && b64d(k);
    if (key && key.length === keyLength) pairingKey = key;
  } catch (e) {}
}

function forgetDevice() {
  device = null; deviceKey = null; session = null;
  store.set('device', null);
}

function phoneName() {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua) ? 'Android phone'
           : /Mac/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows PC' : /Linux/.test(ua) ? 'Linux device' : 'Phone';
  const browser = /SamsungBrowser/.test(ua) ? 'Samsung Internet' : /Edg/.test(ua) ? 'Edge'
                : /Firefox|FxiOS/.test(ua) ? 'Firefox' : /Chrome|CriOS/.test(ua) ? 'Chrome'
                : /Safari/.test(ua) ? 'Safari' : 'browser';
  return os + ' (' + browser + ')';
}

async function pair() {
  const key = pairingKey;
  pairingKey = null;  // single-use whatever happens
  const msg = seal(key, { t: 'pair', name: phoneName() });
  const code = pairingCode(msg);
  showOverlay('Approve on the laptop', 'Type y in the laptop\'s Phone Remote window if it shows this same code.', code);
  setStatus('Waiting for approval on the laptop…');
  const reply = unseal(key, await request('/api/pair', msg, PAIR_TIMEOUT_MS));
  device = { id: reply.id, key: reply.key, host: reply.host };
  deviceKey = b64d(reply.key);
  store.set('device', device);
}

async function hello() {
  const msg = seal(deviceKey, { t: 'hello' });
  msg.d = device.id;
  const reply = unseal(deviceKey, await request('/api/hello', msg, 5000));
  session = reply.s;
  seq = 0;
}

function connect() {
  if (connecting) return connecting;
  session = null;
  connecting = (async () => {
    try {
      if (device) {
        try {
          await hello();
        } catch (e) {
          if (e.code !== 'unpaired') throw e;
          forgetDevice();
        }
      }
      if (!session && pairingKey) {
        await pair();
        await hello();
      }
      if (!session) {
        showOverlay('Pair this phone', 'Scan the QR code shown on the laptop with your phone\'s camera.', null, true);
        setStatus('Not paired', true);
        return;
      }
      hideOverlay();
      setStatus('Connected to ' + (device.host || 'laptop'));
    } catch (e) {
      if (e.code === 'network') showOverlay('Can\'t reach the laptop', e.message, null, true);
      else showOverlay('Not connected', e.message + ' Then scan the QR code again.', null, true);
      setStatus(e.message, true);
    } finally {
      connecting = null;
    }
  })();
  return connecting;
}

// ---------- Commands: one request in flight, motion batched ----------
let queue = [];
let moveX = 0, moveY = 0, scrollAcc = 0;   // accumulated, not yet sent
let inflight = false;
let pendingLabel = '';

function flushMotion() {
  const dx = Math.trunc(moveX), dy = Math.trunc(moveY);
  if (dx || dy) { queue.push({ a: 'move', dx, dy }); moveX -= dx; moveY -= dy; }
  const sy = Math.trunc(scrollAcc);
  if (sy) { queue.push({ a: 'scroll', dy: sy }); scrollAcc -= sy; }
}

function send(op, label) {
  flushMotion();             // keep ordering: movement before this click/key
  queue.push(op);
  if (label) pendingLabel = label;
  pump();
}

async function pump() {
  if (inflight) return;
  flushMotion();
  if (!queue.length) return;
  if (!session) {            // input while disconnected is dropped, not replayed later
    queue = []; pendingLabel = '';
    connect();
    return;
  }
  const ops = queue, label = pendingLabel;
  queue = []; pendingLabel = '';
  inflight = true;
  try {
    const msg = seal(deviceKey, { t: 'cmd', s: session, q: ++seq, ops });
    msg.d = device.id;
    await request('/api/cmd', msg, 4000);
    if (label) setStatus(label);
    else if (statusEl.classList.contains('err')) setStatus('Connected');
  } catch (e) {
    if (e.code === 'session' || e.code === 'unpaired') connect();
    else setStatus(e.message, true);
  } finally {
    inflight = false;
  }
  if (queue.length) pump();
}
setInterval(pump, SEND_INTERVAL_MS);

document.addEventListener('visibilitychange', () => { if (!document.hidden) connect(); });
window.addEventListener('hashchange', () => { takePairingKeyFromUrl(); if (pairingKey) connect(); });

// ---------- Tabs ----------
function showTab(name) {
  $$('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('main section').forEach(s => s.classList.toggle('active', s.id === 'tab-' + name));
  store.set('tab', name);
}
$$('nav button').forEach(b => b.addEventListener('click', () => { buzz(8); showTab(b.dataset.tab); }));
showTab(store.get('tab', 'slides') === 'pad' ? 'pad' : 'slides');

// ---------- Buttons ----------
let suppressClicksUntil = 0;   // after a swipe, ignore the click it may produce
$$('[data-key]').forEach(b => b.addEventListener('click', () => {
  if (performance.now() < suppressClicksUntil) return;
  buzz();
  send({ a: 'key', k: b.dataset.key }, b.dataset.label || b.textContent.trim());
}));

const holdBtn = $('#hold');
let holding = false;
function setHold(on) {
  holding = on;
  holdBtn.classList.toggle('on', on);
  holdBtn.textContent = on ? 'Release' : 'Hold';
}
holdBtn.addEventListener('click', () => {
  buzz();
  setHold(!holding);
  send({ a: holding ? 'down' : 'up' }, holding ? 'Holding - drag on the pad, tap to drop' : 'Released');
});

$$('[data-click]').forEach(b => b.addEventListener('click', () => {
  buzz();
  setHold(false);
  send({ a: 'click', b: b.dataset.click }, b.dataset.click === 'right' ? 'Right click' : 'Left click');
}));

// ---------- Swipe on the slides tab ----------
const slidesTab = $('#tab-slides');
let swipeStart = null;
slidesTab.addEventListener('touchstart', e => {
  swipeStart = e.touches.length === 1 ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
}, { passive: true });
slidesTab.addEventListener('touchend', e => {
  if (!swipeStart) return;
  const t = e.changedTouches[0];
  const dx = t.clientX - swipeStart.x, dy = t.clientY - swipeStart.y;
  swipeStart = null;
  if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) {
    suppressClicksUntil = performance.now() + 400;
    buzz(20);
    if (dx < 0) send({ a: 'key', k: 'next' }, 'Next ▶ (swipe)');
    else send({ a: 'key', k: 'prev' }, '◀ Back (swipe)');
  }
}, { passive: true });

// ---------- Talk timer (survives page reloads) ----------
const clockEl = $('#clock'), timerBtn = $('#timer-toggle');
let timerStart = store.get('timerStart', null);   // epoch ms while running
let timerBanked = store.get('timerBanked', 0);    // ms accumulated before last start
function elapsedMs() { return timerBanked + (timerStart ? Date.now() - timerStart : 0); }
function saveTimer() { store.set('timerStart', timerStart); store.set('timerBanked', timerBanked); }
function renderTimer() {
  const s = Math.floor(elapsedMs() / 1000);
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
  const pad2 = n => String(n).padStart(2, '0');
  clockEl.textContent = (h ? h + ':' + pad2(m) : pad2(m)) + ':' + pad2(sec);
  timerBtn.textContent = timerStart ? 'Pause' : (elapsedMs() ? 'Resume' : 'Start');
  timerBtn.classList.toggle('running', !!timerStart);
}
timerBtn.addEventListener('click', () => {
  buzz();
  if (timerStart) { timerBanked = elapsedMs(); timerStart = null; }
  else timerStart = Date.now();
  saveTimer(); renderTimer();
});
$('#timer-reset').addEventListener('click', () => {
  buzz();
  timerBanked = 0;
  if (timerStart) timerStart = Date.now();
  saveTimer(); renderTimer();
});
setInterval(renderTimer, 250);
renderTimer();

// ---------- Speed ----------
const speedEl = $('#speed'), speedVal = $('#speed-val');
let speed = Number(store.get('speed', 2));
if (!(speed >= 0.5 && speed <= 5)) speed = 2;
function showSpeed() { speedVal.textContent = speed.toFixed(1) + '×'; }
speedEl.value = speed; showSpeed();
speedEl.addEventListener('input', () => { speed = Number(speedEl.value); showSpeed(); store.set('speed', speed); });

// ---------- Touchpad ----------
const pad = $('#pad');
let gesture = null;
let lastTap = null;   // {t, x, y} of the previous one-finger tap, for double-tap
const textEl = $('#text');
function centroid(touches) {
  let x = 0, y = 0;
  for (const t of touches) { x += t.clientX; y += t.clientY; }
  return { x: x / touches.length, y: y / touches.length };
}
pad.addEventListener('touchstart', e => {
  e.preventDefault();
  const p = centroid(e.touches);
  if (!gesture) gesture = { t0: performance.now(), maxFingers: 0, travel: 0, startX: p.x, startY: p.y };
  gesture.fingers = e.touches.length;
  gesture.maxFingers = Math.max(gesture.maxFingers, e.touches.length);
  gesture.x = p.x; gesture.y = p.y;
  pad.classList.add('touching');
}, { passive: false });

pad.addEventListener('touchmove', e => {
  e.preventDefault();
  if (!gesture) return;
  const p = centroid(e.touches);
  if (e.touches.length !== gesture.fingers) {   // finger added/lifted: re-anchor, no jump
    gesture.fingers = e.touches.length;
    gesture.x = p.x; gesture.y = p.y;
    return;
  }
  const dx = p.x - gesture.x, dy = p.y - gesture.y;
  gesture.x = p.x; gesture.y = p.y;
  gesture.travel += Math.abs(dx) + Math.abs(dy);
  if (gesture.maxFingers === 1) {
    const gain = speed * (1 + ACCEL * Math.min(Math.hypot(dx, dy), 40));
    moveX += dx * gain;
    moveY += dy * gain;
  } else if (gesture.fingers >= 2) {
    scrollAcc += dy * SCROLL_GAIN;   // natural: content follows the fingers
  }
}, { passive: false });

function touchEnd(e) {
  e.preventDefault();
  if (!gesture) return;
  if (e.touches.length) {                       // some fingers still down
    const p = centroid(e.touches);
    gesture.fingers = e.touches.length;
    gesture.x = p.x; gesture.y = p.y;
    return;
  }
  const isTap = e.type === 'touchend' && gesture.travel < TAP_SLOP_PX &&
                performance.now() - gesture.t0 < TAP_MAX_MS;
  if (isTap) {
    buzz();
    if (holding) { setHold(false); send({ a: 'up' }, 'Released'); }
    else if (gesture.maxFingers >= 2) send({ a: 'click', b: 'right' }, 'Right click');
    else {
      const now = performance.now();
      const isDouble = lastTap && now - lastTap.t < DOUBLE_TAP_MS &&
                       Math.hypot(gesture.startX - lastTap.x, gesture.startY - lastTap.y) < DOUBLE_TAP_SLOP_PX;
      lastTap = isDouble ? null : { t: now, x: gesture.startX, y: gesture.startY };
      send({ a: 'click', b: 'left' }, isDouble ? 'Double-click - keyboard ready' : 'Click');
      // Double-clicking usually means "edit this text field", so bring up the
      // phone keyboard. Browsers only allow that inside a tap handler like this one.
      if (isDouble) textEl.focus();
    }
  }
  gesture = null;
  pad.classList.remove('touching');
}
pad.addEventListener('touchend', touchEnd, { passive: false });
pad.addEventListener('touchcancel', touchEnd, { passive: false });

// ---------- Typing ----------
function sendText(withEnter) {
  const s = textEl.value;
  if (!s && !withEnter) return;
  buzz();
  const shown = s.length > 30 ? s.slice(0, 30) + '…' : s;
  if (s) send({ a: 'type', s }, 'Typed: ' + shown);
  if (withEnter) send({ a: 'key', k: 'enter' }, s ? 'Typed + Enter: ' + shown : 'Enter');
  textEl.value = '';
}
// Send button: type the text only. Keep the keyboard open for more typing.
$('#type-form').addEventListener('submit', e => {
  e.preventDefault();
  sendText(false);
  textEl.focus();
});
// The phone keyboard's Enter/Go key: type the text and press Enter, so a
// search box runs the search in one step.
textEl.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing) return;
  e.preventDefault();
  sendText(true);
});

takePairingKeyFromUrl();
connect();
})();
