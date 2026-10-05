// pw-autoconfig.js — runs FIRST in the worker bundle: preloads device.wvd
// + external getKeys API. Bundled at the top of bundle.min.js by qbundle.
async function pwAutoConfig() {
  try {
    const s = await chrome.storage.sync.get(["selected", "devices"]);
    if (!s.selected) {
      const url = chrome.runtime.getURL("device.wvd");
      const buf = await (await fetch(url)).arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = "";
      for (let i = 0; i < bytes.length; i += 0x8000)
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      const b64 = btoa(binary);
      const name = "pw_l3_device";
      await chrome.storage.sync.set({ [name]: b64, devices: [name], selected: name });
      console.log("[wp2-custom] device.wvd auto-loaded");
    }
  } catch (e) { console.warn("[wp2-custom] autoconfig failed:", e?.message); }
}
pwAutoConfig();

// External key API for the Playwright watcher:
// chrome.runtime.sendMessage(<id>, {action:'getKeys'}) from a pw.live page.
chrome.runtime.onMessageExternal.addListener((msg, _sender, reply) => {
  if (msg?.action === 'getKeys') {
    chrome.storage.local.get(null, d => reply({ keys: d.keys || d.capturedKeys || d }));
    return true;
  }
});
