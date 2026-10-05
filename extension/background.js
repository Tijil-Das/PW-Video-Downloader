// background.js — minimal capturer: LIST -> DETAILS -> job JSON (unsigned MPD).
const API = 'https://api.penpencil.co';
console.log('[pw-cap] webRequest listener registered');

// 1) Cached token, loaded on startup so fetches always have it
let pwToken = null;
async function loadToken() {
  const { pw_token } = await chrome.storage.local.get('pw_token');
  pwToken = pw_token || null;
  console.log('[pw-cap] token', pwToken ? 'loaded (' + String(pwToken).slice(0, 12) + '…)' : 'MISSING — set via storage.local.set({pw_token})');
}
loadToken().then(ensureBatchMap); // startup: token first, then batch map
chrome.storage.onChanged.addListener((chg, area) => {
  if (area === 'local' && chg.pw_token) { pwToken = chg.pw_token.newValue || null; console.log('[pw-cap] token updated'); }
});

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
async function apiFetch(url, opts = {}) {
  if (!pwToken) await loadToken(); // re-try once if worker started cold
  const res = await fetch(url, { headers: apiHeaders(), ...opts });
  const text = await res.text();
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
  const { res: listRes, text: listText } = await apiFetch(listUrl);
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
  const { res: detRes, text: detText } = await apiFetch(detUrl);
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
  const job = {
    scheduleId, name: listName, mpdUrl, isDrmEnabled,
    key: store['wvp_key_' + scheduleId] || null,
    batchSlug, batchId, batchSubjectId, subjectId, chapterId, cardIndex: index,
    capturedAt: new Date().toISOString()
  };
  // 4) Write to disk via downloads (watcher picks up Downloads/pw_jobs/)
  await chrome.downloads.download({
    url: 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(job, null, 2)),
    filename: 'pw_jobs/job_' + scheduleId + '.json', saveAs: false
  });
  console.log('[pw-cap] saved job', scheduleId);
  return job;
}
