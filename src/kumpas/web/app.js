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
const MAX_BATCH_OPS = 150;     // below the laptop's limit of 200 per message

// Opened from the internet relay (https://<relay>/r/<room>/) or from the
// laptop itself on the local network (http://<laptop>:8765/)?
const ROOM = (/^\/r\/([A-Za-z0-9_-]{22})\/$/.exec(location.pathname) || [])[1] || null;
// Each laptop (room) keeps its own pairing and settings on this phone. The key
// keeps the app's original name so phones paired before the rename stay paired.
const PREFIX = 'phoneRemote.' + (ROOM ? ROOM + '.' : '');

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(PREFIX + key); return v === null ? fallback : JSON.parse(v); }
    catch (e) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(PREFIX + key, JSON.stringify(value)); } catch (e) {}
  },
};

const statusEl = $('#status'), topbar = $('.topbar');
// The dot in the top bar: amber while connecting, green once the laptop
// answers, red after an error.
function setStatus(msg, isError) {
  statusEl.textContent = msg;
  statusEl.classList.toggle('err', !!isError);
  topbar.classList.toggle('err', !!isError);
  if (isError) topbar.classList.remove('linked');
}
function setLinked() { topbar.classList.add('linked'); }
document.documentElement.classList.toggle('https', location.protocol === 'https:');
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

// ---------- Talking to the laptop: local HTTP, or WebSocket via the relay ----------
class ApiError extends Error {
  constructor(message, code) { super(message); this.code = code; }
}

function request(path, body, timeoutMs) {
  return ROOM ? relayRequest(path, body, timeoutMs) : httpRequest(path, body, timeoutMs);
}

// Over the relay all requests share one WebSocket; replies carry the request id.
let relayWs = null, relayReady = null, relayNextId = 1;
const relayPending = new Map();
let laptopOnline = null;      // what the relay last said about the laptop

function relaySocket() {
  if (relayWs && relayWs.readyState <= WebSocket.OPEN) return relayReady;
  const ws = relayWs = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/phone/' + ROOM);
  relayReady = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { ws.close(); reject(new ApiError('Can\'t reach the internet relay. Is the phone online?', 'network')); }, 10000);
    ws.onopen = () => { clearTimeout(timer); resolve(ws); };
    ws.onerror = () => { clearTimeout(timer); reject(new ApiError('Can\'t reach the internet relay. Is the phone online?', 'network')); };
  });
  relayReady.catch(() => {});
  ws.onmessage = e => {
    let m;
    try { m = JSON.parse(e.data); } catch (err) { return; }
    if (m.t === 'host') {                     // the laptop came online or went away
      const was = laptopOnline;
      laptopOnline = m.online;
      if (!m.online && was) laptopWentOffline();
      if (m.online && was === false) connect();
      return;
    }
    const done = relayPending.get(m.i);
    if (done) { relayPending.delete(m.i); done(m); }
  };
  ws.onclose = () => {
    if (relayWs === ws) relayWs = null;
    for (const done of relayPending.values()) done({ s: 0 });
    relayPending.clear();
  };
  return relayReady;
}

const OFFLINE_TEXT = 'Kumpas on the laptop stopped or lost its internet connection. This page reconnects by itself when it is back.';
function laptopWentOffline() {
  session = null;     // reconnect (and get a fresh session) once it's back
  showOverlay('The laptop is offline', OFFLINE_TEXT, null, true);
  setStatus('The laptop went offline', true);
}

async function relayRequest(path, body, timeoutMs) {
  const ws = await relaySocket();
  const i = relayNextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      relayPending.delete(i);
      reject(new ApiError('Timed out - laptop not responding', 'network'));
    }, timeoutMs);
    relayPending.set(i, m => {
      clearTimeout(timer);
      if (!m.s) return reject(new ApiError('Lost the connection to the internet relay', 'network'));
      const data = m.b || {};
      if (m.s >= 400) return reject(new ApiError(data.error || 'Laptop error ' + m.s, data.code));
      resolve(data);
    });
    try { ws.send(JSON.stringify({ i, p: path, b: body })); }
    catch (e) { relayPending.delete(i); clearTimeout(timer); reject(new ApiError('Lost the connection to the internet relay', 'network')); }
  });
}

async function httpRequest(path, body, timeoutMs) {
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
    if (e instanceof TypeError) throw new ApiError('Cannot reach laptop - same Wi-Fi? Kumpas running?', 'network');
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
let frameSeq = 0;        // screen frames are numbered separately from commands
let cursorSeq = 0;       // and so are cursor-position polls
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
  showOverlay('Approve on the laptop', 'Type y in the laptop\'s Kumpas window if it shows this same code.', code);
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
  frameSeq = 0;
  cursorSeq = 0;
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
      setLinked();
      if (screenOn) frameLoop();
    } catch (e) {
      if (e.code === 'offline') showOverlay('The laptop is offline', OFFLINE_TEXT, null, true);
      else if (e.code === 'network') showOverlay('Can\'t reach the laptop', e.message, null, true);
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

let pendingAbs = null;   // latest touchscreen drag position, not yet sent
function flushMotion() {
  if (pendingAbs) { queue.push(pendingAbs); pendingAbs = null; }
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
  // The laptop takes at most 200 operations per message; a long paste or a big
  // deletion while typing live can queue more, so send them in slices.
  const ops = queue.splice(0, MAX_BATCH_OPS);
  const label = queue.length ? '' : pendingLabel;
  if (!queue.length) pendingLabel = '';
  inflight = true;
  try {
    const msg = seal(deviceKey, { t: 'cmd', s: session, q: ++seq, ops });
    msg.d = device.id;
    await request('/api/cmd', msg, 4000);
    if (label) setStatus(label);
    else if (statusEl.classList.contains('err')) setStatus('Connected');
    setLinked();
  } catch (e) {
    if (e.code === 'session' || e.code === 'unpaired') connect();
    else if (e.code === 'offline') laptopWentOffline();
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
  $$('nav button[data-tab]').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name);
    if (b.dataset.tab === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  $$('main section').forEach(s => s.classList.toggle('active', s.id === 'tab-' + name));
  store.set('tab', name);
}
$$('nav button[data-tab]').forEach(b => b.addEventListener('click', () => { buzz(8); showTab(b.dataset.tab); }));
const savedTab = store.get('tab', 'slides');
showTab(['slides', 'pad', 'media'].includes(savedTab) ? savedTab : 'slides');

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
  // Pointing, choosing a talk length or typing a slide number isn't a swipe.
  const ignore = e.target.closest('#pointer, form, .talk');
  swipeStart = e.touches.length === 1 && !ignore ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
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
// With a talk length set it counts down, and the phone buzzes silently in
// your hand at 5 minutes left, 1 minute left and time up, so you never have
// to look at a clock in front of the audience. Without one it counts up.
const MIN = 60000;
const ALERTS = [   // [ms left, vibration pattern, message, minimum talk length]
  [5 * MIN, [150, 100, 150], '5 minutes left', 10 * MIN],
  [1 * MIN, [150, 100, 150, 100, 150], '1 minute left', 3 * MIN],
  [0, [600, 200, 600, 200, 600], 'Time is up', 0],
];
const clockEl = $('#clock'), timerBtn = $('#timer-toggle'), timerEl = $('.timer');
const timerLabel = $('#timer-label');
const lengthEl = $('#talk-length');
let timerStart = store.get('timerStart', null);   // epoch ms while running
let timerBanked = store.get('timerBanked', 0);    // ms accumulated before last start
let talkMs = Number(store.get('talkMin', 0)) * MIN || 0;
let alertsDone = store.get('alertsDone', []);     // thresholds already announced
lengthEl.value = String(talkMs / MIN);
if (lengthEl.value === '') { talkMs = 0; lengthEl.value = '0'; }

function elapsedMs() { return timerBanked + (timerStart ? Date.now() - timerStart : 0); }
function saveTimer() {
  store.set('timerStart', timerStart); store.set('timerBanked', timerBanked);
  store.set('alertsDone', alertsDone);
}
function activeAlerts() { return talkMs ? ALERTS.filter(a => talkMs >= a[3] && talkMs > a[0]) : []; }
// Mark alerts whose moment has already passed as done, without firing them,
// e.g. after changing the talk length halfway through.
function skipPassedAlerts() {
  const left = talkMs - elapsedMs();
  alertsDone = activeAlerts().filter(a => left <= a[0]).map(a => a[0]);
}
function fmt(ms) {
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
  const pad2 = n => String(n).padStart(2, '0');
  return (h ? h + ':' + pad2(m) : pad2(m)) + ':' + pad2(sec);
}
function renderTimer() {
  const elapsed = elapsedMs();
  if (talkMs) {
    const left = talkMs - elapsed;
    // Round up while counting down so "00:00" means time is really up.
    clockEl.textContent = left > 0 ? fmt(left + 999) : '+' + fmt(-left);
    timerEl.classList.toggle('over', left <= 0);
    timerEl.classList.toggle('warn', left > 0 && left <= Math.min(5 * MIN, talkMs / 4));
    // If several came due at once (the phone was asleep), announce only the latest.
    const due = timerStart ? activeAlerts().filter(a => left <= a[0] && !alertsDone.includes(a[0])) : [];
    if (due.length) {
      const [, pattern, message] = due[due.length - 1];
      alertsDone.push(...due.map(a => a[0])); saveTimer();
      try { if (navigator.vibrate) navigator.vibrate(pattern); } catch (e) {}
      timerEl.classList.remove('flash'); void timerEl.offsetWidth; timerEl.classList.add('flash');
      setStatus(message);
    }
  } else {
    clockEl.textContent = fmt(elapsed);
    timerEl.classList.remove('over', 'warn');
  }
  const label = timerStart ? 'Pause' : (elapsed ? 'Resume' : 'Start');
  if (timerLabel.textContent !== label) {
    timerLabel.textContent = label;
    timerBtn.setAttribute('aria-label', label + ' timer');
  }
  timerBtn.classList.toggle('running', !!timerStart);
}
timerBtn.addEventListener('click', () => {
  buzz();
  if (timerStart) { timerBanked = elapsedMs(); timerStart = null; }
  else timerStart = Date.now();
  saveTimer(); renderTimer(); keepAwake();
});
$('#timer-reset').addEventListener('click', () => {
  buzz();
  timerBanked = 0; alertsDone = [];
  if (timerStart) timerStart = Date.now();
  timerEl.classList.remove('flash');
  saveTimer(); renderTimer();
});
lengthEl.addEventListener('change', () => {
  talkMs = Number(lengthEl.value) * MIN || 0;
  store.set('talkMin', talkMs / MIN);
  skipPassedAlerts(); saveTimer(); renderTimer();
  setStatus(talkMs ? 'Talk length ' + (talkMs / MIN) + ' min: the phone buzzes at 5 min, 1 min and time up'
                   : 'Timer counts up');
});
setInterval(renderTimer, 250);
renderTimer();

// Keep the phone's screen on while the timer runs, where the browser allows
// it (the Wake Lock API needs HTTPS, so this is a no-op over plain HTTP).
let wakeLock = null;
async function keepAwake() {
  if (!('wakeLock' in navigator)) return;
  try {
    if (timerStart && !wakeLock && !document.hidden) {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } else if (!timerStart && wakeLock) {
      await wakeLock.release();
    }
  } catch (e) {}
}
document.addEventListener('visibilitychange', keepAwake);
keepAwake();

// ---------- Go to slide N (PowerPoint, Keynote, Impress, Google Slides) ----------
const gotoEl = $('#goto');
$('#goto-form').addEventListener('submit', e => {
  e.preventDefault();
  const n = Math.trunc(Number(gotoEl.value));
  gotoEl.value = '';
  gotoEl.blur();
  if (!(n >= 1 && n <= 9999)) return;
  buzz();
  send({ a: 'type', s: String(n) });
  send({ a: 'key', k: 'enter' }, 'Go to slide ' + n);
});

// ---------- Speed ----------
const speedEl = $('#speed'), speedVal = $('#speed-val');
let speed = Number(store.get('speed', 2));
if (!(speed >= 0.5 && speed <= 5)) speed = 2;
function showSpeed() { speedVal.textContent = speed.toFixed(1) + '×'; }
speedEl.value = speed; showSpeed();
speedEl.addEventListener('input', () => { speed = Number(speedEl.value); showSpeed(); store.set('speed', speed); });

// ---------- Pointer strip on the slides tab ----------
// Moves the laptop's cursor so you can point at things on the projected
// slide, in any app. Taps do nothing here, so pointing never changes slide.
const pointer = $('#pointer');
let pointAt = null;
pointer.addEventListener('touchstart', e => {
  e.preventDefault();
  const p = centroid(e.touches);
  pointAt = { x: p.x, y: p.y, n: e.touches.length };
  pointer.classList.add('touching');
}, { passive: false });
pointer.addEventListener('touchmove', e => {
  e.preventDefault();
  if (!pointAt) return;
  const p = centroid(e.touches);
  if (e.touches.length !== pointAt.n) { pointAt = { x: p.x, y: p.y, n: e.touches.length }; return; }
  const dx = p.x - pointAt.x, dy = p.y - pointAt.y;
  pointAt.x = p.x; pointAt.y = p.y;
  const gain = speed * (1 + ACCEL * Math.min(Math.hypot(dx, dy), 40));
  moveX += dx * gain;
  moveY += dy * gain;
}, { passive: false });
function pointEnd(e) {
  e.preventDefault();
  if (e.touches.length) {
    const p = centroid(e.touches);
    pointAt = { x: p.x, y: p.y, n: e.touches.length };
    return;
  }
  pointAt = null;
  pointer.classList.remove('touching');
}
pointer.addEventListener('touchend', pointEnd, { passive: false });
pointer.addEventListener('touchcancel', pointEnd, { passive: false });

// ---------- Tilt to point (HTTPS only: browsers hide motion sensors otherwise) ----------
// While a finger holds the pointer strip, turning the phone left/right and
// tilting it up/down moves the cursor, like a laser pointer. Lifting the
// finger is the clutch, so the cursor stays put while you gesture.
const TILT_PX_PER_DEG = 30;     // at the default speed setting
const TILT_DEADZONE = 1.5;      // deg/s; ignores hand tremor and sensor drift
const tiltEl = $('#tilt');
let tiltOn = false, pitch = 30, lastMotion = null;

function tiltDelta(rate, pitchDeg, dt, k) {
  // Turning about the vertical shows up on the phone's z axis when it lies flat
  // and on its y axis when it stands upright, so blend them by the pitch.
  const p = pitchDeg * Math.PI / 180;
  const dead = v => (Math.abs(v) < TILT_DEADZONE ? 0 : v);
  const yaw = dead((rate.alpha || 0) * Math.cos(p) + (rate.gamma || 0) * Math.sin(p));
  const tilt = dead(rate.beta || 0);
  return { dx: -yaw * dt * k, dy: -tilt * dt * k };
}
function onOrientation(e) { if (typeof e.beta === 'number') pitch = Math.max(0, Math.min(90, e.beta)); }
function onMotion(e) {
  if (!pointAt || !e.rotationRate) { lastMotion = null; return; }
  const dt = lastMotion === null ? 0 : (e.timeStamp - lastMotion) / 1000;
  lastMotion = e.timeStamp;
  if (!(dt > 0 && dt < 0.2)) return;
  const d = tiltDelta(e.rotationRate, pitch, dt, TILT_PX_PER_DEG * speed / 2);
  moveX += d.dx;
  moveY += d.dy;
}
function setTilt(on) {
  tiltOn = on;
  tiltEl.checked = on;
  pointer.classList.toggle('tilting', on);
  $('#pointer-hint').textContent = on ? 'Hold here and move the phone to point' : 'Drag here to point with the laptop’s cursor';
  for (const [type, fn] of [['devicemotion', onMotion], ['deviceorientation', onOrientation]]) {
    if (on) window.addEventListener(type, fn); else window.removeEventListener(type, fn);
  }
  store.set('tilt', on);
}
async function askMotionPermission() {
  // iOS asks the user, and only from inside a tap.
  for (const E of [window.DeviceMotionEvent, window.DeviceOrientationEvent]) {
    if (E && typeof E.requestPermission === 'function' && await E.requestPermission() !== 'granted') return false;
  }
  return true;
}
if (window.isSecureContext && 'DeviceMotionEvent' in window) {
  $('#tilt-row').hidden = false;
  tiltEl.addEventListener('change', async () => {
    if (!tiltEl.checked) return setTilt(false);
    let ok = false;
    try { ok = await askMotionPermission(); } catch (e) {}
    setTilt(ok);
    setStatus(ok ? 'Tilt pointing on: hold the strip and move the phone' : 'Motion sensors not allowed', !ok);
  });
  // iOS forgets the permission between visits, so only restore where none is needed.
  if (store.get('tilt', false) && typeof DeviceMotionEvent.requestPermission !== 'function') setTilt(true);
} else {
  $('#tilt-hint').hidden = false;
}

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

// ---------- Typing (live) ----------
// Whatever changes in a text box is typed on the laptop straight away: added
// letters are typed, removed ones become Backspace presses. Comparing the old
// and new text (rather than watching keys) also handles autocorrect, tapped
// suggestions, pasting and edits in the middle of the text, which phone
// keyboards report only as "the text changed".
//
// The box always holds an invisible character at the start. Pressing
// Backspace in an otherwise empty box deletes it, which is the only way to
// notice that press on Android, and we pass it on to the laptop.
const SENTINEL = '​';
const MAX_TYPE_CHARS = 500;          // per operation; the laptop accepts up to 2000
const RESET_AFTER_CHARS = 60;        // start a fresh box after a word this far in
const visible = v => v.split(SENTINEL).join('');

function liveTyping(el) {
  let last = '';                      // what the laptop has been sent, without the sentinel
  // The box is never truly empty, so the browser's placeholder never shows: draw our own.
  const ph = document.createElement('span');
  ph.className = 'ph'; ph.textContent = el.placeholder; ph.setAttribute('aria-hidden', 'true');
  el.after(ph);
  const markEmpty = () => el.form.classList.toggle('empty', !visible(el.value));
  el.addEventListener('input', markEmpty);
  function reset() {
    last = '';
    el.value = SENTINEL;
    try { el.setSelectionRange(1, 1); } catch (e) {}
    markEmpty();
  }
  function typeDiff(now) {
    let p = 0;
    while (p < last.length && p < now.length && last[p] === now[p]) p++;
    const removed = last.length - p, added = now.slice(p);
    for (let i = 0; i < removed; i++) send({ a: 'key', k: 'backspace' });
    for (let i = 0; i < added.length; i += MAX_TYPE_CHARS) send({ a: 'type', s: added.slice(i, i + MAX_TYPE_CHARS) });
    const tail = now.length > 24 ? '…' + now.slice(-24) : now;
    if (removed || added) pendingLabel = 'Typing: ' + (tail || '(deleted)');
    last = now;
  }
  el.addEventListener('input', () => {
    if (!session) {                   // nothing reaches the laptop: don't pretend it did
      reset();
      setStatus('Not connected to the laptop', true);
      connect();
      return;
    }
    const now = visible(el.value);
    if (!el.value.startsWith(SENTINEL)) {
      // The invisible character went: Backspace in an empty box, or a
      // selection that included it. Either way the text before it is gone.
      if (now === last) send({ a: 'key', k: 'backspace' }, 'Backspace');
      else typeDiff(now);
      el.value = SENTINEL + now;
      try { el.setSelectionRange(el.value.length, el.value.length); } catch (e) {}
      return;
    }
    typeDiff(now);
    // Keep the box short, so later corrections stay small; the laptop keeps the text.
    if (now.length > RESET_AFTER_CHARS && /\s$/.test(now)) reset();
  });
  // Enter/Go on the phone keyboard presses Enter on the laptop.
  el.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || e.isComposing) return;
    e.preventDefault();
    send({ a: 'key', k: 'enter' }, 'Enter');
    reset();
  });
  el.form.addEventListener('submit', e => { e.preventDefault(); });
  // Keep the cursor after the invisible character.
  el.addEventListener('focus', () => {
    if (!el.value.startsWith(SENTINEL)) reset();
    requestAnimationFrame(() => { try { if (el.selectionStart === 0) el.setSelectionRange(1, 1); } catch (e) {} });
  });
  reset();
}
liveTyping(textEl);

// ---------- Live view of the laptop screen ----------
// Frames are requested one at a time, only while the view is open and the
// page visible, and arrive encrypted like everything else. Each frame says
// where the mouse pointer is (screen captures leave it out), and we draw it.
const FRAME_INTERVAL_MS = 250, FULL_FRAME_INTERVAL_MS = 150;
// The pointer is polled on its own: ~30 times a second locally, 10 through the
// relay, where every message counts towards its costs.
const CURSOR_INTERVAL_MS = ROOM ? 100 : 30;
const screenView = $('#screen-view'), screenImg = $('#screen-img'), cursorEl = $('#screen-cursor');
const screenMsg = $('#screen-msg'), screenToggle = $('#screen-toggle'), monBtn = $('#screen-mon');
let screenOn = !!store.get('screenOn', false);
let monitor = Number(store.get('monitor', 1)) || 1;
let monitorCount = 1;
let frameLoopRunning = false, frameUrl = null, cursorLoopRunning = false;
// Whether a picture is showing. (Not img.naturalWidth: that drops to 0 while the
// next frame loads, which made the arrow flicker and stopped the pointer polls.)
let haveFrame = false;
let cursorFrac = null;          // [x, y] as fractions of the picture, or null
let localCursorAt = 0;          // when we last moved the pointer ourselves
const sleep = ms => new Promise(r => setTimeout(r, ms));
const isFull = () => screenView.classList.contains('full');

function setScreen(on, start = true) {
  screenOn = on;
  store.set('screenOn', on);
  screenView.hidden = !on;
  screenToggle.classList.toggle('active', on);
  screenToggle.setAttribute('aria-pressed', String(on));
  if (!on && isFull()) setFull(false);
  if (on && start) frameLoop();
}
function monitorLabel() {
  return monitor === 0 ? 'All screens' : 'Screen ' + monitor + ' of ' + monitorCount;
}
function placeCursor() {
  const r = screenImg.getBoundingClientRect(), v = screenView.getBoundingClientRect();
  if (!cursorFrac || !haveFrame || !r.width) { cursorEl.setAttribute('hidden', ''); return; }
  // Scale the arrow with the picture, like the real pointer on a shrunken
  // screen, but keep it big enough to see (and bigger when zoomed in).
  const size = Math.round(Math.min(22, Math.max(10, r.width * 0.014)));
  cursorEl.style.width = cursorEl.style.height = size + 'px';
  const tipX = size * 3 / 24, tipY = size * 2 / 24;   // the arrow's tip in its 24-unit drawing
  cursorEl.removeAttribute('hidden');   // an SVG element: no .hidden property
  cursorEl.style.transform = 'translate(' + (r.left - v.left + cursorFrac[0] * r.width - tipX) + 'px,' +
                             (r.top - v.top + cursorFrac[1] * r.height - tipY) + 'px)';
}
function showFrame(reply) {
  const url = URL.createObjectURL(new Blob([b64d(reply.img)], { type: 'image/jpeg' }));
  screenImg.src = url;
  if (frameUrl) URL.revokeObjectURL(frameUrl);
  frameUrl = url;
  haveFrame = true;
  screenMsg.textContent = '';
  if (reply.m !== monitor) resetZoom();
  monitorCount = reply.n;
  monitor = reply.m;
  monBtn.hidden = monitorCount < 2;
  monBtn.textContent = monitorLabel();
  // Right after a tap or drag, trust our own idea of where the pointer is:
  // the frame may have been captured before the pointer moved.
  // The pointer poll is fresher than a frame, so only use the frame's when it isn't running.
  if (!cursorLoopRunning && performance.now() - localCursorAt > 600) cursorFrac = reply.c || null;
  if (screenImg.complete) placeCursor(); else screenImg.onload = placeCursor;
}
async function cursorLoop() {
  if (cursorLoopRunning) return;
  cursorLoopRunning = true;
  try {
    while (screenOn && !document.hidden && session && haveFrame) {
      const started = performance.now();
      try {
        const msg = seal(deviceKey, { t: 'cursor', s: session, q: ++cursorSeq, m: monitor });
        msg.d = device.id;
        const reply = unseal(deviceKey, await request('/api/cursor', msg, 3000));
        if (reply.m === monitor && performance.now() - localCursorAt > 600) {
          cursorFrac = reply.c || null;
          placeCursor();
        }
      } catch (e) {
        break;   // the frame loop reports problems and restarts this loop
      }
      const wait = CURSOR_INTERVAL_MS - (performance.now() - started);
      if (wait > 0) await sleep(wait);
    }
  } finally {
    cursorLoopRunning = false;
  }
}
async function frameLoop() {
  if (frameLoopRunning) return;
  frameLoopRunning = true;
  try {
    while (screenOn && !document.hidden) {
      if (!session) {
        await connect();
        if (!session) break;
      }
      const started = performance.now(), sentWith = session;
      try {
        // Sharper pictures in fullscreen, and more so when zoomed in.
        const scale = Math.min(window.devicePixelRatio || 1, 2) * (isFull() ? Math.min(zoom.s, 2) : 1);
        const w = Math.min(isFull() ? 1920 : 1280, Math.round(screenView.clientWidth * scale));
        const msg = seal(deviceKey, { t: 'frame', s: session, q: ++frameSeq, m: monitor, w });
        msg.d = device.id;
        showFrame(unseal(deviceKey, await request('/api/frame', msg, 8000)));
        if (!cursorLoopRunning) cursorLoop();
      } catch (e) {
        if (e.code === 'screen') {           // turned off or unsupported on the laptop
          screenImg.removeAttribute('src');
          haveFrame = false;
          cursorEl.setAttribute('hidden', '');
          screenMsg.textContent = e.message + ' Tap to try again.';
          break;
        }
        // Reconnect unless the command channel already did since this request left.
        if (e.code === 'session' || e.code === 'unpaired') { if (session === sentWith) await connect(); continue; }
        screenMsg.textContent = e.message;
        await sleep(1500);
      }
      const wait = (isFull() ? FULL_FRAME_INTERVAL_MS : FRAME_INTERVAL_MS) - (performance.now() - started);
      if (wait > 0) await sleep(wait);
    }
  } finally {
    frameLoopRunning = false;
  }
}
screenToggle.addEventListener('click', () => { buzz(8); setScreen(!screenOn); });
screenView.addEventListener('click', e => {
  if (isFull() || e.target.closest('button, form')) return;
  if (!frameLoopRunning) { screenMsg.textContent = 'Loading…'; frameLoop(); return; }
  screenView.classList.toggle('big');   // tap to enlarge, tap again to shrink
  requestAnimationFrame(placeCursor);
});
monBtn.addEventListener('click', () => {
  buzz(8);
  monitor = monitor >= monitorCount ? 0 : monitor + 1;   // 1, 2, ..., then all screens
  store.set('monitor', monitor);
  monBtn.textContent = monitorLabel();
  resetZoom();
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && screenOn) frameLoop(); });
window.addEventListener('resize', () => { resetZoom(); placeCursor(); });

// ---------- Fullscreen touch control ----------
// The picture of the laptop screen becomes a touchscreen: a tap clicks at
// that spot, holding right-clicks, dragging drags, two fingers scroll, and
// pinching zooms the picture (not the laptop) to hit small targets.
const LONG_PRESS_MS = 550, DOUBLE_TAP_REUSE_PX = 24;
const zoom = { s: 1, tx: 0, ty: 0 };
let touch = null;     // the gesture in progress
let lastTapAt = null; // {t, x, y, p}: reuse its point so double-clicks land on one spot
const tipEl = $('#screen-tip'), typeForm = $('#screen-type'), screenText = $('#screen-text');

function setFull(on) {
  screenView.classList.toggle('full', on);
  screenView.classList.remove('big');
  resetZoom();
  if (on) {
    try {
      const p = screenView.requestFullscreen && screenView.requestFullscreen({ navigationUI: 'hide' });
      if (p && p.then) p.then(() => screen.orientation && screen.orientation.lock &&
                                    screen.orientation.lock('landscape').catch(() => {})).catch(() => {});
    } catch (e) {}
    tipEl.classList.remove('gone');
    setTimeout(() => tipEl.classList.add('gone'), 4000);
    if (!frameLoopRunning) frameLoop();
  } else {
    typeForm.hidden = true;
    try { if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch (e) {}
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
  requestAnimationFrame(placeCursor);
}
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && isFull()) setFull(false); });
$('#screen-full').addEventListener('click', () => { buzz(8); setFull(true); });
$('#screen-exit').addEventListener('click', () => { buzz(8); endDrag(); setFull(false); });
$('#screen-kbd').addEventListener('click', () => {
  buzz(8);
  typeForm.hidden = !typeForm.hidden;
  if (!typeForm.hidden) screenText.focus();
});
liveTyping(screenText);
$('#screen-bksp').addEventListener('click', () => { buzz(); send({ a: 'key', k: 'backspace' }, 'Backspace'); screenText.focus(); });

function resetZoom() { zoom.s = 1; zoom.tx = 0; zoom.ty = 0; applyZoom(); }
function applyZoom() {
  // Keep the zoomed picture covering the spot the unzoomed one occupied.
  const w = screenImg.offsetWidth, h = screenImg.offsetHeight;
  zoom.tx = Math.min(0, Math.max(w * (1 - zoom.s), zoom.tx));
  zoom.ty = Math.min(0, Math.max(h * (1 - zoom.s), zoom.ty));
  screenImg.style.transform = zoom.s === 1 ? '' : 'translate(' + zoom.tx + 'px,' + zoom.ty + 'px) scale(' + zoom.s + ')';
  placeCursor();
}
function picPoint(x, y) {
  const r = screenImg.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const fx = (x - r.left) / r.width, fy = (y - r.top) / r.height;
  if (fx < -0.02 || fx > 1.02 || fy < -0.02 || fy > 1.02) return null;   // outside the picture
  return { x: Math.min(1, Math.max(0, fx)), y: Math.min(1, Math.max(0, fy)) };
}
function absOp(p) { return { a: 'abs', x: Math.round(p.x * 1e4) / 1e4, y: Math.round(p.y * 1e4) / 1e4, m: monitor }; }
function pointAtPicture(p) { cursorFrac = [p.x, p.y]; localCursorAt = performance.now(); placeCursor(); }
const fingerGap = ts => Math.hypot(ts[0].clientX - ts[1].clientX, ts[0].clientY - ts[1].clientY);
function endDrag() {
  if (touch && touch.dragging) { touch.dragging = false; send({ a: 'up' }, 'Dropped'); }
}

screenView.addEventListener('touchstart', e => {
  if (!isFull() || e.target.closest('button, form')) return;
  e.preventDefault();
  const ts = e.touches;
  if (ts.length === 1 && !touch) {
    const t = ts[0];
    touch = { kind: 'one', x0: t.clientX, y0: t.clientY, t0: performance.now(), moved: false, dragging: false, done: false };
    const mine = touch;
    mine.timer = setTimeout(() => {                 // held still: right-click
      if (touch !== mine || mine.moved) return;
      const p = picPoint(mine.x0, mine.y0);
      if (!p) return;
      mine.done = true;
      buzz(30);
      pointAtPicture(p);
      send(absOp(p));
      send({ a: 'click', b: 'right' }, 'Right click');
    }, LONG_PRESS_MS);
  } else if (ts.length >= 2) {
    if (touch) { clearTimeout(touch.timer); endDrag(); }
    const c = centroid(ts);
    const v = screenView.getBoundingClientRect();
    // The picture point under the fingers, in the image's own (unzoomed) pixels.
    const ox = v.left + screenImg.offsetLeft, oy = v.top + screenImg.offsetTop;
    touch = { kind: 'two', t0: performance.now(), c0: c, last: c, gap0: fingerGap(ts), mode: null, s0: zoom.s,
              ox, oy, ux: (c.x - ox - zoom.tx) / zoom.s, uy: (c.y - oy - zoom.ty) / zoom.s };
  }
}, { passive: false });

screenView.addEventListener('touchmove', e => {
  if (!touch || !isFull()) return;
  e.preventDefault();
  if (touch.kind === 'one' && e.touches.length === 1) {
    const t = e.touches[0];
    if (!touch.moved && Math.hypot(t.clientX - touch.x0, t.clientY - touch.y0) > TAP_SLOP_PX) {
      touch.moved = true;
      clearTimeout(touch.timer);
      const p0 = picPoint(touch.x0, touch.y0);
      if (p0 && !touch.done) {                      // press where the finger first landed
        send(absOp(p0));
        send({ a: 'down' }, 'Dragging');
        touch.dragging = true;
      }
    }
    if (touch.dragging) {
      const p = picPoint(t.clientX, t.clientY);
      if (p) { pendingAbs = absOp(p); pointAtPicture(p); }
    }
  } else if (touch.kind === 'two' && e.touches.length >= 2) {
    const c = centroid(e.touches), gap = fingerGap(e.touches);
    if (!touch.mode) {
      if (Math.abs(gap - touch.gap0) > 30) touch.mode = 'zoom';
      else if (Math.hypot(c.x - touch.c0.x, c.y - touch.c0.y) > TAP_SLOP_PX) {
        touch.mode = zoom.s > 1 ? 'pan' : 'scroll';
        const p = picPoint(touch.c0.x, touch.c0.y);
        if (touch.mode === 'scroll' && p) { send(absOp(p)); pointAtPicture(p); }   // scroll what's under the fingers
      }
    }
    if (touch.mode === 'zoom' || touch.mode === 'pan') {
      if (touch.mode === 'zoom') zoom.s = Math.min(5, Math.max(1, touch.s0 * gap / touch.gap0));
      zoom.tx = c.x - touch.ox - zoom.s * touch.ux;
      zoom.ty = c.y - touch.oy - zoom.s * touch.uy;
      applyZoom();
    } else if (touch.mode === 'scroll') {
      scrollAcc += (c.y - touch.last.y) * SCROLL_GAIN;
    }
    touch.last = c;
  }
}, { passive: false });

function screenTouchEnd(e) {
  if (!touch || !isFull()) return;
  e.preventDefault();
  if (touch.kind === 'one') {
    clearTimeout(touch.timer);
    if (touch.dragging) {
      endDrag();
    } else if (!touch.moved && !touch.done && e.type === 'touchend') {
      let p = picPoint(touch.x0, touch.y0);
      const now = performance.now();
      if (p) {
        if (lastTapAt && now - lastTapAt.t < DOUBLE_TAP_MS &&
            Math.hypot(touch.x0 - lastTapAt.x, touch.y0 - lastTapAt.y) < DOUBLE_TAP_REUSE_PX) {
          p = lastTapAt.p;              // same spot, so the laptop sees a double-click
          lastTapAt = null;
        } else {
          lastTapAt = { t: now, x: touch.x0, y: touch.y0, p };
        }
        buzz();
        pointAtPicture(p);
        send(absOp(p));
        send({ a: 'click', b: 'left' }, 'Click');
      }
    }
    touch = null;
  } else if (e.touches.length === 0) {
    // Two fingers tapped without moving: right-click, as on the touchpad.
    if (!touch.mode && e.type === 'touchend' && performance.now() - touch.t0 < TAP_MAX_MS * 1.6) {
      const p = picPoint(touch.c0.x, touch.c0.y);
      if (p) { buzz(); pointAtPicture(p); send(absOp(p)); send({ a: 'click', b: 'right' }, 'Right click'); }
    }
    touch = null;
  }
}
screenView.addEventListener('touchend', screenTouchEnd, { passive: false });
screenView.addEventListener('touchcancel', screenTouchEnd, { passive: false });

setScreen(screenOn, false);   // connect() starts the frames once connected

takePairingKeyFromUrl();
connect();
})();
