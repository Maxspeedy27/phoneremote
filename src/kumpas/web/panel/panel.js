(() => {
'use strict';
const $ = s => document.querySelector(s);

// The secret token arrives in the URL fragment; keep it for reloads of this tab only.
let token = new URLSearchParams(location.hash.slice(1)).get('t');
try {
  if (token) sessionStorage.setItem('panelToken', token);
  else token = sessionStorage.getItem('panelToken');
} catch (e) {}
history.replaceState(null, '', '/');

async function api(action, body) {
  const r = await fetch('/api/' + action, {
    method: 'POST', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-Panel-Token': token || '' },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || 'Error ' + r.status);
  return data;
}

function text(el, value) { if (el.textContent !== value) el.textContent = value; }
function show(el, on) { el.hidden = !on; }
const fmtTime = t => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const fmtDate = t => new Date(t * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

let lastQrUrl = null, lastAddresses = '', lastPendingCode = null, lastLog = '';
let pendingTotal = 60;   // seconds the current pairing request had when it appeared
let chosenMode = null;   // 'relay' or 'local' once the user picks a tab; else automatic
let busy = false;   // don't let a poll overwrite a switch the user is changing

function render(s) {
  text($('#version'), s.version ? 'v' + s.version : '');
  show($('#problem'), !!s.problem);
  if (s.problem) text($('#problem'), s.problem);

  const running = !!s.url;
  show($('#pair-card'), running);
  for (const el of document.querySelectorAll('.stack, footer #backend')) show(el, running);
  if (running) {
    // Which QR code: through the internet relay when it's online, else local.
    const relayUp = s.relay.state === 'online' && !!s.relay.url;
    const mode = relayUp ? (chosenMode || 'relay') : 'local';
    show($('#qr-tabs'), relayUp);
    for (const b of document.querySelectorAll('#qr-tabs button')) b.setAttribute('aria-selected', String(b.dataset.mode === mode));
    const qrUrl = mode === 'relay' ? s.relay.url : s.url, qrSvg = mode === 'relay' ? s.relay.qr : s.qr;
    if (qrUrl !== lastQrUrl && qrSvg) {
      $('#qr').src = 'data:image/svg+xml;base64,' + btoa(qrSvg);
      lastQrUrl = qrUrl;
    }
    text($('#pair-help'), mode === 'relay'
      ? 'Scan this code with the phone\'s camera. Works on any network: Wi-Fi or mobile data.'
      : 'Scan this code with the phone\'s camera. The phone needs to be ' + s.network + '.');
    show($('#local-only'), mode === 'local');
    text($('#base'), s.base);

    show($('#relay-setting'), s.relay.available);
    if (!busy) $('#relay-on').checked = s.relay.enabled;
    const note = $('#relay-note');
    text(note, !s.relay.enabled ? 'Off: phones must be on the same Wi-Fi as this laptop.'
      : s.relay.state === 'online' ? 'Online: phones can connect from any network.'
      : s.relay.state === 'connecting' ? 'Connecting\u2026'
      : 'Can\'t reach the internet right now. Phones on the same Wi-Fi still work; this retries by itself.');
    note.classList.toggle('ok-text', s.relay.enabled && s.relay.state === 'online');
    note.classList.toggle('warn-text', s.relay.enabled && s.relay.state === 'offline');
    text($('#pair-title'), s.device ? 'Pair a different phone' : 'Pair your phone');
    const addrKey = JSON.stringify(s.addresses) + s.ip;
    if (addrKey !== lastAddresses) {
      const sel = $('#address');
      sel.replaceChildren(...s.addresses.map(a => {
        const o = document.createElement('option');
        o.value = a.ip; o.textContent = a.ip + (a.kind ? ' (' + a.kind + ')' : '');
        return o;
      }));
      if (!s.addresses.some(a => a.ip === s.ip)) {
        const o = document.createElement('option'); o.value = s.ip; o.textContent = s.ip; sel.prepend(o);
      }
      sel.value = s.ip;
      lastAddresses = addrKey;
    }

    text($('#device'), s.device ? s.device.name + ' · paired ' + fmtDate(s.device.paired_at)
                                : 'No phone yet. Scan the code to pair one.');
    show($('#forget'), !!s.device);

    if (!busy) {
      $('#screen-on').checked = s.screen.on;
      $('#https-on').checked = s.https.on;
    }
    show($('#viewing'), s.screen.viewing);
    text($('#screen-note'), s.screen.problem ||
      'Shows a live picture of the laptop screen on the phone, encrypted, only while you look at it.');
    $('#screen-note').classList.toggle('warn-text', !!s.screen.problem);
    show($('#fingerprint'), !!s.https.fingerprint);
    if (s.https.fingerprint) text($('#fingerprint'), 'Certificate fingerprint (SHA-256): ' + s.https.fingerprint);
    if (s.https.problem) text($('#https-note'), s.https.problem);
    text($('#backend'), 'Input: ' + s.backend);
    show($('#access'), s.accessibility === false);

    const pill = $('#pill');
    pill.className = 'pill' + (s.pending ? ' wait' : s.screen.viewing ? ' live' : s.device ? ' ok' : '');
    text(pill, s.pending ? 'Waiting for you' : s.screen.viewing ? 'Screen shared' : s.device ? 'Ready' : 'Not paired');
  } else {
    text($('#pill'), 'Not running');
  }

  // Pairing request
  const p = s.pending;
  show($('#pending'), !!p);
  if (p) {
    text($('#pending-name'), p.name);
    text($('#pending-code'), p.code.slice(0, 3) + ' ' + p.code.slice(3));
    text($('#pending-left'), p.left + ' s left');
    if (p.code !== lastPendingCode) {
      lastPendingCode = p.code;
      pendingTotal = Math.max(p.left, 1);
      $('#allow').focus();
      notify(p);
    }
    $('#pending-bar').style.width = Math.max(0, Math.min(100, 100 * p.left / pendingTotal)) + '%';
  } else {
    lastPendingCode = null;
  }
  document.title = p ? '(!) Approve phone - Kumpas' : 'Kumpas';

  const logKey = JSON.stringify(s.log);
  if (logKey !== lastLog) {
    lastLog = logKey;
    $('#log').replaceChildren(...(s.log.length ? s.log : [{ t: Date.now() / 1000, text: 'Started.' }]).map(e => {
      const li = document.createElement('li');
      const time = document.createElement('time');
      time.textContent = fmtTime(e.t);
      const span = document.createElement('span');
      span.textContent = e.text;
      li.append(time, span);
      return li;
    }));
  }
}

function notify(p) {
  if (!document.hidden || !('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    const n = new Notification('Kumpas: approve ' + p.name + '?',
                               { body: 'Code ' + p.code.slice(0, 3) + ' ' + p.code.slice(3), requireInteraction: true });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (e) {}
}
// Ask once, on the first click, so pairing requests can alert you in another tab.
document.addEventListener('click', () => {
  try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch (e) {}
}, { once: true });

let stopped = false, lastState = null;
// Fetch and show the current state once (also used right after a button press).
async function refresh() {
  if (stopped) return;
  try {
    render(lastState = await api('state'));
  } catch (e) {
    text($('#pill'), 'Not responding');
    if (/forbidden/.test(e.message)) {
      stopped = true;
      text($('#problem'), 'This tab has lost its connection to the app. Open Kumpas again.');
      show($('#problem'), true);
    }
  }
}
// The one polling loop.
async function poll() {
  await refresh();
  if (!stopped) setTimeout(poll, 800);
}

async function act(action, body) {
  try { return await api(action, body); }
  catch (e) { text($('#problem'), e.message); show($('#problem'), true); }
}

$('#allow').addEventListener('click', () => act('answer', { allow: true }).then(refresh));
$('#refuse').addEventListener('click', () => act('answer', { allow: false }).then(refresh));
$('#forget').addEventListener('click', () => {
  if (confirm('Forget the paired phone? It will need to scan the QR code again.')) act('forget');
});
$('#address').addEventListener('change', e => act('address', { ip: e.target.value }));
$('#access-open').addEventListener('click', () => act('accessibility'));
for (const b of document.querySelectorAll('#qr-tabs button')) {
  b.addEventListener('click', () => { chosenMode = b.dataset.mode; lastQrUrl = null; if (lastState) render(lastState); });
}
for (const [id, action] of [['#screen-on', 'screen'], ['#https-on', 'https'], ['#relay-on', 'relay']]) {
  $(id).addEventListener('change', async e => {
    busy = true;
    const r = await act(action, { on: e.target.checked });
    if (r && r.ok === false && r.error) { e.target.checked = false; text($('#https-note'), r.error); }
    busy = false;
  });
}
$('#quit').addEventListener('click', async () => {
  await act('quit');
  stopped = true;
  show($('#stopped'), true);
});

poll();
})();
