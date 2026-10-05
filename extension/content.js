// content.js — hover + Ctrl+Shift+D capture (runs on pw.live)
let mouseX = 0, mouseY = 0;
document.addEventListener('mousemove', e => { mouseX = e.clientX; mouseY = e.clientY; }, { passive: true });

// Toast helper
function toast(msg, ok = false) {
  document.getElementById('pw-cap-toast')?.remove();
  const t = document.createElement('div');
  t.id = 'pw-cap-toast';
  t.textContent = msg;
  t.style.cssText = `position:fixed;z-index:999999;left:50%;bottom:32px;transform:translateX(-50%);padding:10px 16px;border-radius:8px;font:14px sans-serif;color:#fff;background:${ok ? '#16a34a' : '#dc2626'};box-shadow:0 4px 16px rgba(0,0,0,.3)`;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

// Green check overlay on card for 1s
function markCard(card) {
  const b = document.createElement('div');
  b.textContent = '✓ captured';
  b.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(22,163,74,.25);color:#fff;font:bold 16px sans-serif;z-index:5;border-radius:8px;pointer-events:none';
  const prev = card.style.position;
  if (!prev || prev === 'static') card.style.position = 'relative';
  card.appendChild(b);
  setTimeout(() => { b.remove(); card.style.position = prev; }, 1000);
}

function capture() {
  const el = document.elementFromPoint(mouseX, mouseY);
  const card = el?.closest?.('div[class*="_card_"]');
  if (!card) { toast('Hover over a lecture card first'); return; }
  const cards = Array.from(document.querySelectorAll('div[class*="_card_"]'));
  const index = cards.indexOf(card);
  const name = card.querySelector('span[class*="_titleText_"]')?.textContent?.trim() || '';
  // batchSlug from path /batches/<slug>/ ; ids from query params
  const m = location.pathname.match(/\/batches\/([^/]+)/);
  const q = new URLSearchParams(location.search);
  const msg = {
    type: 'PW_CAPTURE', batchSlug: m?.[1] || '',
    batchSubjectId: q.get('batchSubjectId') || '',
    subjectId: q.get('subjectId') || '',
    chapterId: q.get('chapterId') || '',
    index, name
  };
  chrome.runtime.sendMessage(msg, res => {
    if (chrome.runtime.lastError || !res?.ok) toast('Capture failed: ' + (res?.error || chrome.runtime.lastError?.message || 'unknown'));
    else { toast('Saved job ' + res.scheduleId.slice(0, 8) + '…', true); markCard(card); }
  });
}

document.addEventListener('keydown', e => {
  if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) { e.preventDefault(); capture(); }
});
// Also respond to command shortcut via background (some layouts skip keydown)
chrome.runtime.onMessage.addListener((msg, _s, reply) => {
  if (msg?.type === 'PW_CAPTURE_CMD') { capture(); reply?.({ ok: true }); }
});

// STEP 1+2 fallback — scan page storages for token-like values, log exact keys.
// Report: which storage holds a token (>100 chars containing eyJ) or a refresh key.
function scanPwToken() {
  const out = { cookies: document.cookie ? document.cookie.split(';').length : 0, hits: [] };
  const isTok = v => typeof v === 'string' && v.length > 100 && v.includes('eyJ');
  const isRef = (k, v) => typeof v === 'string' && v.length > 20 && /refresh/i.test(k);
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const v = localStorage.getItem(k);
      if (isTok(v)) { out.hits.push({ store: 'localStorage', key: k, len: v.length, kind: 'access?' }); console.log('[pw-cap] token-like localStorage key:', k, 'len', v.length); }
      else if (isRef(k, v)) { out.hits.push({ store: 'localStorage', key: k, len: v.length, kind: 'refresh?' }); console.log('[pw-cap] refresh-like localStorage key:', k, 'len', v.length); }
    }
  } catch (e) { console.log('[pw-cap] localStorage scan skipped:', e?.message); }
  try {
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i);
      const v = sessionStorage.getItem(k);
      if (isTok(v)) { out.hits.push({ store: 'sessionStorage', key: k, len: v.length, kind: 'access?' }); console.log('[pw-cap] token-like sessionStorage key:', k, 'len', v.length); }
      else if (isRef(k, v)) { out.hits.push({ store: 'sessionStorage', key: k, len: v.length, kind: 'refresh?' }); console.log('[pw-cap] refresh-like sessionStorage key:', k, 'len', v.length); }
    }
  } catch (e) { console.log('[pw-cap] sessionStorage scan skipped:', e?.message); }
  // cookies: names only (HttpOnly values invisible to content script)
  try {
    for (const part of (document.cookie || '').split(';')) {
      const k = part.split('=')[0]?.trim();
      if (k) console.log('[pw-cap] cookie visible:', k);
    }
  } catch (e) {}
  // IndexedDB: async — list database names only (values need per-DB read)
  try {
    if (indexedDB?.databases) indexedDB.databases().then(dbs => console.log('[pw-cap] IndexedDB DBs:', (dbs || []).map(d => d.name).join(',')));
  } catch (e) {}
  if (!out.hits.length) console.log('[pw-cap] scan: NO token-like (>100ch+eyJ) or refresh-like values in web storages');
  return out;
}
chrome.runtime.onMessage.addListener((msg, _s, reply) => {
  if (msg?.type === 'PW_REHARVEST_TOKEN') {
    try {
      const found = scanPwToken();
      // Return best access candidate value so background can adopt it live.
      let token = null;
      const pick = (store) => (found.hits.find(h => h.store === store && h.kind === 'access?') || found.hits.find(h => h.store === store));
      const hit = pick('localStorage') || pick('sessionStorage');
      if (hit) {
        try { token = (hit.store === 'localStorage' ? localStorage : sessionStorage).getItem(hit.key); } catch (e) {}
      }
      reply?.({ ok: true, token: token || null, hits: found.hits });
    } catch (e) { reply?.({ ok: false, error: String(e?.message || e) }); }
    return true;
  }
  if (msg?.type === 'PW_SCAN_TOKENS') { const r = scanPwToken(); reply?.({ ok: true, ...r }); return true; }
  if (msg?.type === 'PW_SESSION_EXPIRED') { toast('Session expired — please log in to pw.live again'); reply?.({ ok: true }); }
  if (msg?.type === 'PW_JOB_STATUS') { showJobStatus(msg); reply?.({ ok: true }); return true; }
  if (msg?.type === 'PW_APP_DOWN') { showAppDown(msg?.message); reply?.({ ok: true }); return true; }
});

// Live job overlay on the hovered card (pointer-events:none, auto-clear 5s)
let jobOverlayTimer = null;
function cardUnderCursor() {
  const el = document.elementFromPoint(mouseX, mouseY);
  return el?.closest?.('div[class*="_card_"]') || document.querySelector('div[class*="_card_"]');
}
function paintOverlay(text, bg) {
  const card = cardUnderCursor();
  if (!card) { toast(text); return; }
  let o = card.querySelector(':scope > .pw-job-overlay');
  if (!o) {
    o = document.createElement('div');
    o.className = 'pw-job-overlay';
    o.style.cssText = 'position:absolute;inset:auto 8px 8px 8px;display:flex;align-items:center;justify-content:center;padding:6px 10px;border-radius:8px;font:bold 13px sans-serif;color:#fff;z-index:6;pointer-events:none';
    const prev = card.style.position;
    if (!prev || prev === 'static') card.style.position = 'relative';
    card.appendChild(o);
  }
  o.textContent = text;
  o.style.background = bg;
  clearTimeout(jobOverlayTimer);
}
function showJobStatus(m) {
  const map = {
    queued: ['⏳ queued', 'rgba(87,83,78,.92)'],
    signing: ['🔑 signing', 'rgba(87,83,78,.92)'],
    downloading: [`⬇ ${m.pct ?? 0}%`, 'rgba(30,64,175,.92)'],
    decrypting: ['🔓 decrypting', 'rgba(30,64,175,.92)'],
    done: ['✓ saved', 'rgba(22,163,74,.92)'],
    error: ['✗ ' + (m.message || m.detail || 'error').slice(0, 60), 'rgba(220,38,38,.92)'],
  };
  const [text, bg] = map[m.stage] || [String(m.stage || '…'), 'rgba(36,49,80,.92)'];
  paintOverlay(text, bg);
  if (m.stage === 'done' || m.stage === 'error')
    jobOverlayTimer = setTimeout(() => document.querySelectorAll('.pw-job-overlay').forEach((o) => o.remove()), 5000);
}
function showAppDown(message) {
  paintOverlay('⚠ ' + (message || 'App not running — start the PW Downloader desktop app'), 'rgba(220,38,38,.92)');
  jobOverlayTimer = setTimeout(() => document.querySelectorAll('.pw-job-overlay').forEach((o) => o.remove()), 5000);
}
