// background.js — minimal capturer: LIST -> DETAILS -> job JSON (unsigned MPD).
const API = 'https://api.penpencil.co';
console.log('[pw-cap] webRequest listener registered');

// 1) Cached token, loaded on startup so fetches always have it
let pwToken = null;
let pwRefreshToken = null;
// Verified 2026-10-05 from pw.har (276 entries) + pw-auth-web-sdk.main.CA6PoG5A.js:
// refresh candidates NOT FOUND — POST /v3/oauth/token: NOT FOUND,
// POST /v1/oauth/refresh: NOT FOUND, POST /v3/oauth/refresh: NOT FOUND.
// HAR shows only POST /v3/oauth/verify-token {randomId,organizationId}->{isVerified},
// and real calls carry NO Authorization header (client-id/client-type path only).
// So NO fabricated endpoint: fallback = live-reharvest the page's current token.
async function loadToken() {
  const { pw_token, pw_refresh_token } = await chrome.storage.local.get(['pw_token', 'pw_refresh_token']);
  pwToken = pw_token || null;
  pwRefreshToken = pw_refresh_token || null;
  console.log('[pw-cap] token', pwToken ? 'loaded (' + String(pwToken).slice(0, 12) + '…)' : 'MISSING — set via storage.local.set({pw_token})');
}
loadToken().then(ensureBatchMap); // startup: token first, then batch map
chrome.storage.onChanged.addListener((chg, area) => {
  if (area !== 'local') return;
  if (chg.pw_token) { pwToken = chg.pw_token.newValue || null; console.log('[pw-cap] token updated'); }
  if (chg.pw_refresh_token) { pwRefreshToken = chg.pw_refresh_token.newValue || null; console.log('[pw-cap] refresh token updated'); }
});

// JWT expiry (base64 payload exp). Returns 0 when not a JWT / no exp.
function jwtExp(token) {
  try {
    const part = String(token).split('.')[1];
    if (!part) return 0;
    const json = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')));
    return Number(json.exp) || 0;
  } catch (e) { return 0; }
}

// Ask an open pw.live tab's content script for the page's current token
// (live-reharvest fallback — no refresh endpoint exists to call).
async function reharvestFromTabs() {
  try {
    const tabs = await chrome.tabs.query({ url: 'https://www.pw.live/*' });
    for (const t of tabs) {
      try {
        const r = await chrome.tabs.sendMessage(t.id, { type: 'PW_REHARVEST_TOKEN' });
        if (r?.token && String(r.token).length > 20) {
          console.log('[pw-cap] reharvested token from tab', t.id, '(' + String(r.token).slice(0, 12) + '…)');
          return String(r.token);
        }
      } catch (e) {}
    }
  } catch (e) { console.log('[pw-cap] reharvest tabs skipped:', e?.message); }
  // chrome.cookies fallback (needs "cookies" permission if added later)
  try {
    if (chrome.cookies?.getAll) {
      const all = await chrome.cookies.getAll({ domain: 'pw.live' });
      console.log('[pw-cap] pw.live cookies visible:', all.map(c => c.name).join(',') || '(none)');
      const hit = all.find(c => c.value && c.value.length > 100 && c.value.includes('eyJ'));
      if (hit) { console.log('[pw-cap] token-like cookie:', hit.name); return hit.value; }
    }
  } catch (e) { console.log('[pw-cap] cookie read skipped:', e?.message); }
  return null;
}

// Attempted refresh path (only used IF a refresh token was ever stored).
// Endpoint NOT FOUND in HAR/SDK, so this tries the documented-shape call
// best-effort and falls back to reharvest; never fabricates success.
async function tryStoredRefresh() {
  if (!pwRefreshToken) return null;
  console.log('[pw-cap] attempting stored-refresh (best-effort, endpoint unverified)...');
  try {
    const res = await fetch(API + '/v3/oauth/refresh', {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ grant_type: 'refresh_token', refresh_token: pwRefreshToken })
    });
    const text = await res.text();
    if (!res.ok) { console.log('[pw-cap] refresh failed', res.status, text.slice(0, 200)); return null; }
    const j = JSON.parse(text);
    const access = j?.data?.accessToken || j?.data?.token || j?.accessToken || j?.token || null;
    const rotated = j?.data?.refreshToken || j?.refreshToken || null;
    if (access) {
      pwToken = access;
      const upd = { pw_token: access };
      if (rotated) { pwRefreshToken = rotated; upd.pw_refresh_token = rotated; }
      await chrome.storage.local.set(upd);
      console.log('[pw-cap] token refreshed (' + String(access).slice(0, 12) + '…)');
      return access;
    }
  } catch (e) { console.log('[pw-cap] refresh attempt error:', e?.message); }
  return null;
}

async function ensureFreshToken() {
  if (!pwToken) await loadToken();
  if (pwToken) {
    const exp = jwtExp(pwToken);
    const now = Math.floor(Date.now() / 1000);
    if (!exp || exp >= now + 60) { pushTokenToApp(pwToken, 'capture'); return pwToken; }
    console.log('[pw-cap] token expiring soon (exp', exp, 'now', now + '), renewing...');
  }
  // 1) stored refresh token if present (best-effort)
  const viaRefresh = await tryStoredRefresh();
  if (viaRefresh) return viaRefresh;
  // 2) live-reharvest from open pw.live tab
  const live = await reharvestFromTabs();
  if (live) {
    pwToken = live;
    await chrome.storage.local.set({ pw_token: live });
    console.log('[pw-cap] adopted live page token');
    pushTokenToApp(live, 'reharvest');
    return live;
  }
  return pwToken;
}

// Push the fresh Bearer into the desktop token_store over the live socket.
function pushTokenToApp(token, source) {
  try {
    if (wsConnected && ws?.readyState === 1 && token)
      ws.send(JSON.stringify({ type: 'token_update', token, source: source || 'capture' }));
  } catch (e) {}
}

async function sessionExpired(tabId) {
  console.log('[pw-cap] refresh failed, clearing tokens');
  pwToken = null; pwRefreshToken = null;
  try { await chrome.storage.local.remove(['pw_token', 'pw_refresh_token']); } catch (e) {}
  try {
    if (tabId) await chrome.tabs.sendMessage(tabId, { type: 'PW_SESSION_EXPIRED' });
    else {
      const tabs = await chrome.tabs.query({ url: 'https://www.pw.live/*' });
      for (const t of tabs) { try { await chrome.tabs.sendMessage(t.id, { type: 'PW_SESSION_EXPIRED' }); } catch (e) {} }
    }
  } catch (e) {}
  console.log('[pw-cap] Session expired — please log in to pw.live again.');
}

// 2+3) Every api.penpencil.co fetch goes through here with full header set
function apiHeaders() {
  const h = {
    'client-id': '5eb393ee95fab7468a79d189', 'client-type': 'WEB',
    'client-version': '3219', 'version': '3.2.19', 'x-sdk-version': '0.0.20',
    'randomid': crypto.randomUUID(),
    'Origin': 'https://www.pw.live', 'Referer': 'https://www.pw.live/',
    'Content-Type': 'application/json'
  };
  if (pwToken) h['Authorization'] = 'Bearer ' + pwToken; // 2) Bearer on every call
  return h;
}
async function apiFetch(url, opts = {}, senderTabId = null, _retried = false) {
  await ensureFreshToken(); // silent renew before each call (JWT exp check + reharvest)
  const res = await fetch(url, { headers: apiHeaders(), ...opts });
  const text = await res.text();
  if ((res.status === 401 || res.status === 403) && !_retried) {
    console.log('[pw-cap] 401/403, attempting silent renew + single retry...');
    pwToken = null;
    await ensureFreshToken();
    const res2 = await fetch(url, { headers: apiHeaders(), ...opts });
    const text2 = await res2.text();
    if (res2.status === 401 || res2.status === 403) {
      console.log('[pw-cap] refresh failed, clearing tokens');
      await sessionExpired(senderTabId);
    }
    return { res: res2, text: text2 };
  }
  return { res, text };
}

// --- passive signed-URL cache (observes normal browsing; never drives tabs) ---
chrome.webRequest.onBeforeRequest.addListener(details => {
  if (!details.url.includes('master.mpd')) return;
  if (!details.url.includes('Signature=') && !details.url.includes('URLPrefix=')) return;
  const uuid = (details.url.match(/cloudfront\.net\/([^/]+)\//) || [])[1];
  if (!uuid) return;
  chrome.storage.local.get('signed_urls').then(({ signed_urls = {} }) => {
    signed_urls[uuid] = details.url;
    chrome.storage.local.set({ signed_urls });
    console.log('[pw-cap] cached signed URL for', uuid.slice(0, 8) + '…');
  });
}, { urls: ['https://d1d34p8vz63oiq.cloudfront.net/*'] });

// Slug -> hex batchId map (page URL has slug like mission-100-jee-2027-225226,
// LIST/DETAILS APIs need the hex id like 6aa790b23e605f161edbf979)
let batchMap = {};
let purchasedSample = null;
function collectSlugKeys(item, out) {
  for (const v of [item.slug, item.batchSlug, item.url, item.name, item.batchName, item.code, item.title])
    if (typeof v === 'string' && v) out.push(v);
  // fallback: any string field that looks slug-ish (catches urls like .../batches/<slug>)
  const scan = o => {
    if (typeof o === 'string') { if (o.length > 5 && o.length < 200 && /[a-z0-9]-[a-z0-9]/i.test(o)) out.push(o); return; }
    if (Array.isArray(o)) { o.forEach(scan); return; }
    if (o && typeof o === 'object') Object.values(o).forEach(scan);
  };
  scan(item);
}
function buildBatchMap(json) {
  const arr = Array.isArray(json?.data) ? json.data
    : Array.isArray(json?.data?.batches) ? json.data.batches
    : Array.isArray(json?.data?.purchases) ? json.data.purchases
    : Array.isArray(json) ? json : [];
  const map = {};
  for (const item of arr) {
    const id = item?._id || item?.id || item?.batchId || item?.batch?._id;
    if (!id) continue;
    const keys = [];
    collectSlugKeys(item, keys);
    for (const k of keys)
      for (const v of [k, String(k).toLowerCase(), String(k).split('/batches/')[1]?.split(/[/?#]/)[0]].filter(Boolean))
        if (!(v in map)) map[v] = id;
  }
  return { map, first: arr[0] || null };
}
async function ensureBatchMap() {
  const cached = await chrome.storage.local.get('batch_map');
  if (cached.batch_map && Object.keys(cached.batch_map).length) { batchMap = cached.batch_map; return batchMap; }
  try {
    const { res, text } = await apiFetch(`${API}/batch-service/v1/batches/purchased-batches?amount=paid&page=1&type=ALL`);
    console.log('[pw-cap] purchased-batches', res.status, text.slice(0, 300));
    if (!res.ok) return batchMap;
    const { map, first } = buildBatchMap(JSON.parse(text));
    purchasedSample = first;
    batchMap = map;
    await chrome.storage.local.set({ batch_map: map });
    console.log('[pw-cap] batch map entries:', Object.keys(map).length);
  } catch (e) { console.warn('[pw-cap] batch map fetch failed:', e.message); }
  return batchMap;
}
function resolveBatchId(slug) {
  if (batchMap[slug]) return batchMap[slug];
  const low = String(slug).toLowerCase();
  if (batchMap[low]) return batchMap[low];
  for (const k of Object.keys(batchMap)) {
    const kl = k.toLowerCase();
    if (low.includes(kl) || kl.includes(low)) return batchMap[k];
  }
  return null;
}

// Keyboard command -> forward to active tab's content script
chrome.commands.onCommand.addListener(async cmd => {
  if (cmd !== 'capture-lecture') return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: 'PW_CAPTURE_CMD' }).catch(() => console.warn('[pw-cap] content script not ready'));
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg?.type !== 'PW_CAPTURE') return;
  handleCapture(msg, sender?.tab?.id).then(job => reply({ ok: true, scheduleId: job.scheduleId }))
    .catch(err => reply({ ok: false, error: String(err?.message || err) }));
  return true; // async reply
});

async function handleCapture({ batchSlug, batchSubjectId, subjectId, chapterId, index, name }, senderTabId) {
  if (!batchSubjectId || index == null || index < 0) throw new Error('missing ids/card index');
  // Resolve slug -> hex batchId via purchased-batches map
  await ensureBatchMap();
  const resolved = resolveBatchId(batchSlug);
  if (resolved) console.log('[pw-cap] resolved batchId', resolved);
  else {
    console.warn('[pw-cap] no match for slug', batchSlug);
    if (purchasedSample) console.log('[pw-cap] sample item:', JSON.stringify(purchasedSample).slice(0, 500));
  }
  const batchId = resolved || batchSlug;

  // 1) LIST — big limit so card index is covered
  const listUrl = `${API}/batch-service/v3/batch-subject-schedules/${batchId}/subject/${batchSubjectId}/contents?skip=0&limit=100&contentType=LECTURES&tagId=${chapterId}`;
  const { res: listRes, text: listText } = await apiFetch(listUrl, {}, senderTabId);
  // 4) Log status + first 300 chars of body
  console.log('[pw-cap] LIST', listRes.status, listText.slice(0, 300));
  if (!listRes.ok) throw new Error('LIST failed: HTTP ' + listRes.status + ' ' + listText.slice(0, 120));
  const list = JSON.parse(listText);
  const item = list?.data?.[index];
  if (!item?._id) throw new Error('no lecture at index ' + index);
  const scheduleId = item._id, listName = item.topic || item.videoDetails?.name || name;
  const listDrm = item.videoDetails?.drmProtected ?? null;

  // 2) DETAILS (same header wrapper)
  const detUrl = `${API}/v1/batches/${batchId}/subject/${batchSubjectId}/schedule/${scheduleId}/schedule-details`;
  const { res: detRes, text: detText } = await apiFetch(detUrl, {}, senderTabId);
  console.log('[pw-cap] DETAILS', detRes.status, detText.slice(0, 300));
  if (!detRes.ok) throw new Error('DETAILS failed: HTTP ' + detRes.status);
  const d = JSON.parse(detText)?.data || {};
  // 1) Log the RAW url values before any processing
  console.log('[pw-cap] raw data.url:', d.url);
  console.log('[pw-cap] raw videoDetails.videoUrl:', d.videoDetails?.videoUrl);
  let mpdUrl = d.url || d.videoDetails?.videoUrl || null;
  if (!mpdUrl) throw new Error('no MPD url in schedule-details');
  // Prefer a cached signed URL if the user already played this lecture;
  // otherwise save unsigned — the Playwright watcher signs it.
  const videoUuid = (mpdUrl.match(/cloudfront\.net\/([^/]+)\//) || [])[1];
  const { signed_urls = {} } = await chrome.storage.local.get('signed_urls');
  if (videoUuid && signed_urls[videoUuid]) {
    mpdUrl = signed_urls[videoUuid];
    console.log('[pw-cap] using cached signed URL [SIGNED ✓]');
  } else {
    console.log('[pw-cap] unsigned MPD saved; watcher will sign it [UNSIGNED]');
  }
  const isDrmEnabled = d.isDrmEnabled ?? d.videoDetails?.drmProtected ?? listDrm;

  // 3) Optional Widevine key if WidevineProxy2 cached one (best-effort)
  const store = await chrome.storage.local.get('wvp_key_' + scheduleId);
  const thumb = d.thumbnail || d.videoDetails?.thumbnail || d.poster || null;
  const job = {
    scheduleId, name: listName, mpdUrl, isDrmEnabled,
    key: store['wvp_key_' + scheduleId] || null,
    batchSlug, batchId, batchSubjectId, subjectId, chapterId, cardIndex: index,
    thumbnailUrl: thumb, capturedAt: new Date().toISOString()
  };
  // 4) Send to desktop app over WebSocket (falls back to file if app down)
  if (wsConnected && ws?.readyState === 1) {
    const jobId = scheduleId;
    ws.send(JSON.stringify({ type: 'job', jobId, ...job }));
    console.log('[pw-cap] sent job to app', jobId);
    try { await chrome.tabs.sendMessage(senderTabId, { type: 'PW_JOB_STATUS', jobId, stage: 'queued', pct: 0, detail: 'queued' }); } catch (e) {}
  } else {
    try { await chrome.tabs.sendMessage(senderTabId, { type: 'PW_APP_DOWN', message: 'PW Downloader app is not running' }); } catch (e) {}
    console.log('[pw-cap] app not running — saving job file as fallback');
    await chrome.downloads.download({
      url: 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(job, null, 2)),
      filename: 'pw_jobs/job_' + scheduleId + '.json', saveAs: false
    });
  }
  console.log('[pw-cap] saved job', scheduleId);
  return job;
}

// --- WebSocket client to desktop app (MV3-safe: reconnect + keepalive) ---
// Token handshake SKIPPED (personal tool; server checks Origin header).
// WS traffic keeps the service worker alive (Chrome 116+ resets 30s idle).
let ws = null, wsConnected = false, wsDelay = 1000, wsPort = 9777;
try { chrome.storage.local.get('ws_port').then((r) => { if (r?.ws_port) wsPort = Number(r.ws_port); }); } catch (e) {}
function wsUrl() { return 'ws://127.0.0.1:' + wsPort; }
function connectWS() {
  try { if (ws && (ws.readyState === 0 || ws.readyState === 1)) return; } catch (e) {}
  try { ws = new WebSocket(wsUrl()); } catch (e) { scheduleWS(); return; }
  ws.onopen = () => {
    wsConnected = true; wsDelay = 1000;
    console.log('[pw-cap] WS connected to app');
    try { ws.send(JSON.stringify({ type: 'hello' })); } catch (e) {}
  };
  ws.onmessage = (e) => {
    let msg = null;
    try { msg = JSON.parse(e.data); } catch (err) { return; }
    if (msg.type === 'ping') { try { ws.send(JSON.stringify({ type: 'pong' })); } catch (err) {} return; }
    if (msg.type === 'welcome' || msg.type === 'ack') return;
    if (['status', 'done', 'error'].includes(msg.type)) {
      // BUGFIX: sendMessage throws if the tab's content script went stale
      // (navigation); query fresh + catch per-tab so one dead tab can't
      // swallow the update meant for the visible card.
      (async () => {
        let tabs = [];
        try { tabs = await chrome.tabs.query({ url: 'https://www.pw.live/*' }); } catch (err) { return; }
        await Promise.all(tabs.map(async (t) => {
          try { await chrome.tabs.sendMessage(t.id, { type: 'PW_JOB_STATUS', ...msg }); }
          catch (err) {
            // Stale content script: re-inject then retry once.
            try {
              await chrome.scripting.executeScript({ target: { tabId: t.id }, files: ['content.js'] });
              await chrome.tabs.sendMessage(t.id, { type: 'PW_JOB_STATUS', ...msg });
            } catch (e2) {}
          }
        }));
      })();
    }
  };
  ws.onclose = () => { wsConnected = false; scheduleWS(); };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}
function scheduleWS() {
  setTimeout(connectWS, wsDelay);
  wsDelay = Math.min(wsDelay * 2, 30000);
}
connectWS();
// Keepalive alarm (MV3 may suspend idle workers; alarm + WS traffic wakes it)
try {
  chrome.alarms?.create('pw-ws-keep', { periodInMinutes: 0.5 });
  chrome.alarms?.onAlarm.addListener((a) => { if (a?.name === 'pw-ws-keep') connectWS(); });
} catch (e) {}
