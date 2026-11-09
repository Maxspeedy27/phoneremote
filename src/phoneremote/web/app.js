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
let frameSeq = 0;        // screen frames are numbered separately from commands
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
  frameSeq = 0;
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
      setStatus('Connected to ' + (device.host || 'laptop') + (location.protocol === 'https:' ? ' 🔒' : ''));
      if (screenOn) frameLoop();
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
  $$('nav button[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
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
      setStatus('⏰ ' + message);
    }
  } else {
    clockEl.textContent = fmt(elapsed);
    timerEl.classList.remove('over', 'warn');
  }
  timerBtn.textContent = timerStart ? 'Pause' : (elapsed ? 'Resume' : 'Start');
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

// ---------- Live view of the laptop screen ----------
// Frames are requested one at a time, only while the view is open and the
// page visible, and arrive encrypted like everything else.
const FRAME_INTERVAL_MS = 250;
const screenView = $('#screen-view'), screenImg = $('#screen-img');
const screenMsg = $('#screen-msg'), screenToggle = $('#screen-toggle'), monBtn = $('#screen-mon');
let screenOn = !!store.get('screenOn', false);
let monitor = Number(store.get('monitor', 1)) || 1;
let monitorCount = 1;
let frameLoopRunning = false, frameUrl = null;
const sleep = ms => new Promise(r => setTimeout(r, ms));

function setScreen(on, start = true) {
  screenOn = on;
  store.set('screenOn', on);
  screenView.hidden = !on;
  screenToggle.classList.toggle('active', on);
  screenToggle.setAttribute('aria-pressed', String(on));
  if (on && start) frameLoop();
}
function showFrame(reply) {
  const url = URL.createObjectURL(new Blob([b64d(reply.img)], { type: 'image/jpeg' }));
  screenImg.src = url;
  if (frameUrl) URL.revokeObjectURL(frameUrl);
  frameUrl = url;
  screenMsg.textContent = '';
  monitorCount = reply.n;
  monitor = reply.m;
  monBtn.hidden = monitorCount < 2;
  monBtn.textContent = monitor === 0 ? 'All screens' : 'Screen ' + monitor + ' of ' + monitorCount;
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
        const scale = Math.min(window.devicePixelRatio || 1, 2);
        const w = Math.min(1280, Math.round(screenView.clientWidth * scale));
        const msg = seal(deviceKey, { t: 'frame', s: session, q: ++frameSeq, m: monitor, w });
        msg.d = device.id;
        showFrame(unseal(deviceKey, await request('/api/frame', msg, 8000)));
      } catch (e) {
        if (e.code === 'screen') {           // turned off or unsupported on the laptop
          screenImg.removeAttribute('src');
          screenMsg.textContent = e.message + ' Tap to try again.';
          break;
        }
        // Reconnect unless the command channel already did since this request left.
        if (e.code === 'session' || e.code === 'unpaired') { if (session === sentWith) await connect(); continue; }
        screenMsg.textContent = e.message;
        await sleep(1500);
      }
      const wait = FRAME_INTERVAL_MS - (performance.now() - started);
      if (wait > 0) await sleep(wait);
    }
  } finally {
    frameLoopRunning = false;
  }
}
screenToggle.addEventListener('click', () => { buzz(8); setScreen(!screenOn); });
screenView.addEventListener('click', e => {
  if (e.target === monBtn) return;
  if (!frameLoopRunning) { screenMsg.textContent = 'Loading…'; frameLoop(); return; }
  screenView.classList.toggle('big');   // tap to enlarge, tap again to shrink
});
monBtn.addEventListener('click', () => {
  buzz(8);
  monitor = monitor >= monitorCount ? 0 : monitor + 1;   // 1, 2, ..., then all screens
  store.set('monitor', monitor);
  monBtn.textContent = monitor === 0 ? 'All screens' : 'Screen ' + monitor + ' of ' + monitorCount;
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && screenOn) frameLoop(); });
setScreen(screenOn, false);   // connect() starts the frames once connected

takePairingKeyFromUrl();
connect();
})();
