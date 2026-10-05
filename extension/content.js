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
