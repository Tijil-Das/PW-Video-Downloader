"""PW watcher part 1/2: config, watch URL, KID parse."""
import json, re, time, traceback, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text())
PROFILE_DIR = r"C:\Users\tijil\pw-chrome-profile"
JOBS = Path(CFG["jobs_dir"]); OUT = Path(CFG["output_dir"])
OUT.mkdir(parents=True, exist_ok=True); JOBS.mkdir(parents=True, exist_ok=True)

def watch_url(j):
    s = j["scheduleId"]
    return (f"https://www.pw.live/watch/?batchSlug={j['batchId']}&batchSubjectId={j['batchSubjectId']}"
            f"&subjectSlug={j['batchSubjectId']}&topicSlug=all&scheduleId={s}&type=penpencilvdo"
            f"&isPPJEnabled=true&entryPoint=BATCH_LECTURE_VIDEOS_{s}&learn2Earn=true"
            f"&parentId={j['batchId']}&vType=BATCHES&childId={s}")

def kid_from_mpd(mpd_url):
    try:
        xml = urllib.request.urlopen(urllib.request.Request(
            mpd_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pw.live/",
                              "Origin": "https://www.pw.live"})).read().decode("utf-8", "replace")
        m = re.search(r"[Dd][Ee][Ff][Aa][Uu][Ll][Tt]_KID=\"([0-9a-fA-F-]{32,36})\"", xml)
        if m: return m.group(1).replace("-", "").lower()
    except Exception as e: print(f"[watcher] KID parse skipped: {e}", flush=True)
    return None

def capture(job):
    """Official Chrome via remote-debugging: signed URL sniff + Widevine key read.
    Hibbiki has NO usable Widevine (page itself reports 'No Widevine support'),
    so we drive the real Chrome (full CDM) over CDP on a dedicated profile."""
    from playwright.sync_api import sync_playwright
    import subprocess as sp
    signed, login_wait = [], CFG.get("login_wait_seconds", 300) * 1000
    prof = Path(CFG["chrome_profile_dir"])
    exe = CFG.get("chromium_executable")
    if not exe or not Path(exe).exists():
        print(f"[watcher] ERROR: Chrome not found at {exe}", flush=True)
        return None, None, None
    CDP_PORT = 9333
    silent = CFG.get("silent", True)  # headless shell: no window, keeps CDM + extensions
    chrome_proc = sp.Popen(
        [exe, f"--user-data-dir={prof}", f"--remote-debugging-port={CDP_PORT}",
         "--no-first-run", "--no-default-browser-check",
         "--autoplay-policy=no-user-gesture-required",
         "--disable-features=CrossOriginMediaPlaybackRequiresUserGesture",
         "--mute-audio"]
        + (["--headless=new", "--disable-gpu", "--window-size=1280,800"] if silent else ["about:blank"]),
        stdout=sp.DEVNULL, stderr=sp.DEVNULL,
        creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
    print(f"[watcher] official Chrome launched ({'SILENT' if silent else 'VISIBLE'} pid {chrome_proc.pid}, CDP :{CDP_PORT})", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}", timeout=30000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        # stealth: hide automation flags so PW's devtool-detector doesn't blank the player
        try:
            ctx.add_init_script("""() => {
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = window.chrome || { runtime: {} };
                const origOpen = window.open;
            }""")
        except Exception as e: print(f"[watcher] stealth script skipped: {e}", flush=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # FIX1: auto-dismiss any JS dialog before it can crash the driver
        try: page.on("dialog", lambda d: d.dismiss())
        except Exception as e: print(f"[watcher] dialog handler skipped: {e}", flush=True)
        # early failure hooks: catch console/errors/failed requests from first navigation
        try:
            page.on("console", lambda m: print(f"[watcher] EARLY-{m.type}: {m.text[:200]}", flush=True)
                    if m.type in ("error",) and "bing.com" not in m.text
                    and "encryption_key_material" not in m.text else None)
            # WP2 key hook: its MAIN-world script logs "[WVP2] ... Widevine Keys [...]"
            # when it re-signs a challenge. Surface that even at log/info level.
            page.on("console", lambda m: print(f"[watcher] WP2-HOOK: {m.text[:300]}", flush=True)
                    if "WVP2" in m.text or "Widevine Keys" in m.text else None)
            page.on("pageerror", lambda e: print(f"[watcher] EARLY-ERROR: {str(e)[:300]}", flush=True))
            page.on("requestfailed", lambda r: print(f"[watcher] EARLY-REQ-FAIL: {r.url[:140]} :: {r.failure}", flush=True)
                    if "google" not in r.url and "bing" not in r.url and "snapchat" not in r.url
                    and "unleash" not in r.url and "clarity" not in r.url
                    and "doubleclick" not in r.url and "csp" not in (r.failure or "") else None)
        except Exception as e: print(f"[watcher] early listeners skipped: {e}", flush=True)
        # FIX2: CDM verification FIRST, on a throwaway page (before PW navigation)
        print("[watcher] checking Widevine CDM...", flush=True)
        try:
            chk = ctx.new_page()
            chk.goto("chrome://components/")
            chk.wait_for_timeout(4000)
            # wait until at least 2 component rows render (Widevine loads async)
            try: chk.wait_for_function("() => document.body && document.body.innerText.split('Version:').length > 2", timeout=10000)
            except Exception: pass
            wv_version = chk.evaluate("""() => {
                const txt = document.body ? document.body.innerText : '';
                const i = txt.toLowerCase().indexOf('widevine');
                if (i < 0) return 'Widevine row MISSING; visible rows: ' + txt.slice(0,200);
                return txt.slice(Math.max(0,i-60), i+160);
            }""")
            print(f"[watcher] Widevine CDM version: {str(wv_version)[:300]}", flush=True)
            if wv_version in ("0.0.0.0", "not found"):
                print("[watcher] Widevine CDM NOT installed. Clicking 'Check for updates'...", flush=True)
                try:
                    chk.evaluate("""() => {
                        const rows = document.querySelectorAll('.component');
                        for (const row of rows) {
                            if (row.textContent.includes('Widevine')) {
                                const btn = row.querySelector('button');
                                if (btn) btn.click();
                                return;
                            }
                        }
                    }""")
                    chk.wait_for_timeout(8000)
                    chk.reload()
                    chk.wait_for_timeout(2500)
                    wv2 = chk.evaluate("() => document.body ? document.body.innerText.slice(0,400) : 'no-body'")
                    print(f"[watcher] CDM after update attempt: {str(wv2)[:300]}", flush=True)
                except Exception as e2: print(f"[watcher] CDM update click failed: {e2}", flush=True)
            chk.close()
        except Exception as e: print(f"[watcher] CDM pre-check skipped: {e}", flush=True)
        print(f"[watcher] Chrome running ({'SILENT' if silent else 'VISIBLE'})", flush=True)
        if not silent:
            try: page.bring_to_front()
            except Exception: pass
        # SIGNED-URL SNIFF: register BEFORE navigation (player fetches MPD on load,
        # before any play click — the old post-detection registration missed it).
        page.on("request", lambda r: signed.append(r.url)
                if ("master.mpd" in r.url and ("Signature=" in r.url or "URLPrefix=" in r.url)
                    and not signed) else None)
        page.on("response", lambda r: print(f"[watcher] license-ish: {r.status} {r.url[:160]}", flush=True)
                if any(k in r.url.lower() for k in ("widevine", "license", "/drm", "playready", "drm-")) else None)
        # LICENSE BODY SNIFF: capture challenge + response bytes for pywidevine-direct.
        # If WP2 never hooks the page, we replay the license ourselves with device.wvd.
        lic = {"challenge": None, "response": None}
        def _lic_req(r):
            u = r.url.lower()
            if any(k in u for k in ("widevine", "license", "/drm/", "playready")) and r.method == "POST":
                try:
                    pd = r.post_data
                    if pd: lic["challenge"] = {"url": r.url, "data": pd[:20000]}
                except Exception: pass
        def _lic_res(r):
            u = r.url.lower()
            if any(k in u for k in ("widevine", "license", "/drm/", "playready")):
                print(f"[watcher] LICENSE-URL: {r.status} {r.url[:160]}", flush=True)
        try:
            page.on("request", _lic_req)
            page.on("response", _lic_res)
        except Exception as e: print(f"[watcher] license hooks skipped: {e}", flush=True)
        print(f"[watcher] profile: {CFG['chrome_profile_dir']}", flush=True)
        # WP2 PRE-FLIGHT (must run BEFORE goto): locate worker, re-reg scripts,
        # verify the MAIN-world hook on a blank page. If the probe is false here,
        # the watch page would miss interception too -> abort early, never corrupt.
        wp2_id = None
        sw = None
        try:
            for w in ctx.service_workers:
                if "library/background/bundle.min.js" in w.url:
                    sw = w
                    break
            if not sw:
                try: sw = ctx.wait_for_event("serviceworker", timeout=10000)
                except Exception: pass
            if sw:
                wp2_id = sw.url.split("/")[2]
                print(f"[watcher] wp2_id detected: {wp2_id}", flush=True)
                re = sw.evaluate("""() => (async () => {
                    try {
                        const cur = await chrome.scripting.getRegisteredContentScripts();
                        await chrome.scripting.unregisterContentScripts({ ids: cur.map(s => s.id) });
                        await chrome.scripting.registerContentScripts([
                            { id: 'WVP2_ISOLATED', matches: ['<all_urls>'],
                              js: ['library/isolated/bundle.min.js'],
                              runAt: 'document_start', world: 'ISOLATED',
                              allFrames: true, matchOriginAsFallback: true, persistAcrossSessions: true },
                            { id: 'WVP2_MAIN', matches: ['<all_urls>'],
                              js: ['library/main/bundle.min.js'],
                              runAt: 'document_start', world: 'MAIN',
                              allFrames: true, matchOriginAsFallback: true, persistAcrossSessions: true }
                        ]);
                        return 're-registered';
                    } catch (e) { return 're-reg FAILED: ' + e.message; }
                })()""")
                print(f"[watcher] WP2 re-reg: {str(re)[:120]}", flush=True)
                # DEBUG-TABLE FIX: video plays + no keys + Challenge/License status
                # = "unable to intercept messages" -> try proxy mode PROPERTY.
                # Event mode clones + re-dispatches; property mode overrides the
                # message getter in place (works when stopImmediatePropagation fails).
                pm = sw.evaluate("""() => new Promise(r => {
                    chrome.storage.sync.set({ proxy_mode: 'property' }, () => r('property-set'));
                })""")
                print(f"[watcher] WP2 proxy_mode: {str(pm)[:60]}", flush=True)
                probe0 = page.evaluate("""() => !!(window.MediaKeySession &&
                    window.MediaKeySession.prototype.generateRequest &&
                    window.MediaKeySession.prototype.generateRequest.toString().includes('Proxy'))""")
                print(f"[watcher] pre-flight MAIN probe: {probe0}", flush=True)
            else:
                print("[watcher] WP2 NOT installed - aborting before corrupt download", flush=True)
                return None, None, None
        except Exception as e:
            print(f"[watcher] WP2 pre-flight failed: {e}", flush=True)
            return None, None, None
        page.goto(watch_url(job), wait_until="domcontentloaded")
        print("[watcher] waiting for login/dashboard...", flush=True)
        try: page.wait_for_function(
            "() => document.querySelector('video') !== null || location.href.includes('/watch/')",
            timeout=login_wait)
        except Exception: print("[watcher] login wait timed out, trying sniff anyway...", flush=True)
        # SNIFF FIRST, probe CDM after: playback must start to trigger license;
        # EME probe consumes no CDM session and runs fine after sniff.
        # EME check ON THE PW PAGE (no robustness: Hibbiki/non-VMP rejects SW_SECURE_*).
        # Plain query only verifies CDM presence; real playback is the true test.
        # Wrapped in retry: the probe can race an SPA navigation (context destroyed).
        wv = "SKIPPED"
        for _eme_try in range(3):
            try:
                wv = page.evaluate("""async () => {
          try {
            const access = await navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{
              initDataTypes: ['cenc'],
              videoCapabilities: [{contentType: 'video/mp4; codecs="avc1.42E01E"'}],
              audioCapabilities: [{contentType: 'audio/mp4; codecs="mp4a.40.2"'}]
            }]);
            return 'OK: ' + access.keySystem;
          } catch (e) { return 'FAIL: ' + e.name + ' - ' + e.message; }
        }""")
                print(f"[watcher] Widevine EME check: {wv}", flush=True)
                break
            except Exception as e:
                print(f"[watcher] EME probe raced navigation, retry {_eme_try+1}/3: {e}", flush=True)
                page.wait_for_timeout(2000)
        # FIX: reload the page if the EME probe raced navigation (context destroyed).
        # The sniff hooks survive; the signed URL fires on the fresh load.
        # CDM component version via chrome://components
        try:
            cp = ctx.new_page()
            cp.goto("chrome://components", wait_until="domcontentloaded")
            cp.wait_for_timeout(1500)
            ver = cp.evaluate("() => document.documentElement.innerText.match(/Widevine[^\\n]*\\n[^\\n]*/)?.[0] || 'not found'")
            print(f"[watcher] Widevine CDM version: {ver}", flush=True)
            cp.close()
        except Exception as e: print(f"[watcher] CDM version check skipped: {e}", flush=True)
        if str(wv).startswith("FAIL"):
            print("[watcher] WARNING: EME probe failed - continuing anyway (real playback is the true test)", flush=True)
            print("[watcher]   (continuing anyway - CDM may still load for real playback)", flush=True)
            print("[watcher]   (real playback is the true test, not this probe)", flush=True)
            print("[watcher]   sniffing signed URL next regardless", flush=True)
        wp2_id = wp2_id  # from pre-flight above; re-verify worker still alive
        try:
            print(f"[watcher] DEBUG wp2_id: {wp2_id}", flush=True)
        except Exception as e: print(f"[watcher] DEBUG worker list failed: {e}", flush=True)
        # WP2 health check: is it enabled + does it have a device selected?
        # If the MAIN-world script never logs [WVP2], interception is off.
        if wp2_id and sw:
            try:
                health = sw.evaluate("""() => new Promise(r => {
                    chrome.storage.sync.get(['selected','devices','enabled'], s => r(JSON.stringify(s)));
                })""")
                print(f"[watcher] WP2 health: {str(health)[:200]}", flush=True)
            except Exception as e: print(f"[watcher] WP2 health check failed: {e}", flush=True)
        # (signed-URL + license hooks already registered pre-navigation above)
        print("[watcher] player detected, sniffing signed URL...", flush=True)
        page.wait_for_timeout(2000)
        # NOTE: early hooks (EARLY-*) already cover console/errors; no duplicate registration here.
        # wait for React hydration: body text OR video OR player chrome, up to 30s
        try:
            page.wait_for_function(
                "() => (document.body && document.body.innerText.trim().length > 50) || document.querySelector('video') || document.querySelector('[class*=player i], [class*=video i] video, video-js')",
                timeout=30000)
            print("[watcher] page hydrated (body/video present)", flush=True)
        except Exception: print("[watcher] hydration wait timed out - page still blank", flush=True)
        # CDM needs a moment after EME-OK before the player retries the license;
        # the signed MPD fires on that retry, so settle before clicking play.
        page.wait_for_timeout(5000)
        # FIX: click the player's Play button in DOM, then force-play + unpause loop
        try:
            clicked = page.evaluate("""() => {
                const out = [];
                const roots = [document];
                // descend into same-origin iframes + shadow roots
                for (const f of document.querySelectorAll('iframe')) {
                    try { if (f.contentDocument) roots.push(f.contentDocument); } catch(e) {}
                }
                const scan = (root) => {
                    const els = root.querySelectorAll
                        ? root.querySelectorAll('button, div[role="button"], video, svg, [aria-label]')
                        : [];
                    for (const el of els) {
                        if (el.shadowRoot) roots.push(el.shadowRoot);
                        const t = ((el.getAttribute && el.getAttribute('aria-label')) || el.textContent || '').toLowerCase();
                        if (/play/.test(t) && el.offsetParent !== null) {
                            try { el.click(); out.push('click:' + t.slice(0,40)); return true; } catch(e) {}
                        }
                        if (el.tagName === 'VIDEO') {
                            try { el.muted = true; el.volume = 0; el.play().catch(()=>{}); out.push('video.play()'); } catch(e) {}
                        }
                    }
                    return false;
                };
                for (const r of roots) { if (scan(r)) break; }
                const frames = [...document.querySelectorAll('iframe')].length;
                out.push('iframes=' + frames);
                return out.join('|') || 'nothing-clicked';
            }""")
            print(f"[watcher] play trigger: {clicked}", flush=True)
            try:
                diag = page.evaluate("""() => {
                    const o = {};
                    o.url = location.href.slice(0,120);
                    o.title = document.title.slice(0,80);
                    o.videos = document.querySelectorAll('video').length;
                    o.iframes = [...document.querySelectorAll('iframe')].map(f => (f.src||'').slice(0,100));
                    o.players = document.querySelectorAll('[class*="player" i], [id*="player" i], [class*="video" i], video-js, shaka-player').length;
                    o.btns = [...document.querySelectorAll('button')].slice(0,8).map(b => ((b.getAttribute('aria-label')||b.textContent||'').trim().slice(0,30)));
                    o.shaka = !!document.querySelector('shaka-player, video[src*=".mpd"], video[src*="cloudfront"]');
                    o.scripts = [...document.querySelectorAll('script[src]')].slice(-4).map(s => (s.src||'').slice(-60));
                    o.errs = (window.__pwErrors||[]).slice(-3);
                    o.bodyLen = document.body ? document.body.innerHTML.length : 0;
                    o.bodyHead = document.body ? document.body.innerText.slice(0,300) : 'no-body';
                    return JSON.stringify(o);
                }""")
                print(f"[watcher] DOM diag: {diag}", flush=True)
            except Exception as e: print(f"[watcher] diag failed: {e}", flush=True)
            # MAIN-world probe: does WP2's hook exist on this page?
            try:
                probe = page.evaluate("""() => {
                    const o = {};
                    o.hasGenerateRequestProxy = !!(window.MediaKeySession &&
                        window.MediaKeySession.prototype &&
                        window.MediaKeySession.prototype.generateRequest &&
                        window.MediaKeySession.prototype.generateRequest.toString().includes('Proxy'));
                    o.wvp2Flag = !!document.querySelector('script[src*="bundle.min.js"]');
                    o.mediaKeys = typeof window.MediaKeys !== 'undefined';
                    return JSON.stringify(o);
                }""")
                print(f"[watcher] MAIN-world probe: {probe}", flush=True)
            except Exception as e: print(f"[watcher] probe failed: {e}", flush=True)
            # EME SESSION SPY: what key systems/sessions does the player actually use?
            # If PW uses ClearKey or a raw CDM session, WP2's Widevine hook never fires.
            try:
                spy = page.evaluate("""() => {
                    const o = { sessions: [] };
                    try {
                        const v = document.querySelector('video');
                        o.videoKeys = !!(v && v.mediaKeys);
                    } catch(e) { o.videoKeys = 'err'; }
                    return JSON.stringify(o);
                }""")
                print(f"[watcher] EME spy: {spy}", flush=True)
            except Exception as e: print(f"[watcher] spy failed: {e}", flush=True)
        except Exception as e: print(f"[watcher] play trigger failed: {e}", flush=True)
        try:
            for _ in range(10):
                st = page.evaluate("""() => {
                    const docs = [document];
                    for (const f of document.querySelectorAll('iframe')) {
                        try { if (f.contentDocument) docs.push(f.contentDocument); } catch(e) {}
                    }
                    for (const d of docs) {
                        const v = d.querySelector ? d.querySelector('video') : null;
                        if (v) {
                            if (v.paused) { v.muted = true; v.play().catch(()=>{}); }
                            return (v.paused ? 'paused' : 'playing') + ' t=' + Math.round(v.currentTime||0) + ' src=' + (v.currentSrc||v.src||'').slice(-60);
                        }
                    }
                    return 'no-video iframes=' + document.querySelectorAll('iframe').length;
                }""")
                print(f"[watcher] video state: {st}", flush=True)
                if isinstance(st, str) and st.startswith("playing"): break
                page.wait_for_timeout(1000)
        except Exception as e: print(f"[watcher] play loop skipped: {e}", flush=True)
        try:
            while not signed: page.wait_for_timeout(1000)
        except Exception as e:
            print(f"[watcher] page died during sniff: {e}", flush=True)
            if not signed:
                print("[watcher] no signed URL captured - page crashed", flush=True)
                browser.close()
                return None, kid_from_mpd(job.get("mpdUrl", "")), None
        print("[watcher] signed URL captured", flush=True)
        kid = kid_from_mpd(signed[0]) or kid_from_mpd(job.get("mpdUrl", ""))
        print(f"[watcher] DEBUG KID: {kid}", flush=True)
        key = None
        # --- NEW: Read keys directly from the WP2 service worker ---
        print("[watcher] reading keys from service worker storage...", flush=True)
        key = None
        if ctx.service_workers:
            sw = None
            for w in ctx.service_workers:  # prefer the WP2 worker
                if wp2_id and wp2_id in w.url: sw = w; break
            sw = sw or ctx.service_workers[0]
        # WP2 needs time for the license exchange; poll up to 30s for the KID match.
        want = (kid or "").replace("-", "").lower()
        for attempt in range(30):
            try:
                storage_dump = sw.evaluate("() => new Promise(r => chrome.storage.local.get(null, d => r(d)))")
                for storage_key, value in (storage_dump or {}).items():
                    entries = []
                    if isinstance(value, dict) and isinstance(value.get("keys"), list):
                        entries = value["keys"]
                    elif isinstance(value, list):
                        entries = value
                    for e in entries:
                        if not isinstance(e, dict): continue
                        ekid = str(e.get("kid", "")).replace("-", "").lower()
                        ek = str(e.get("k", "")).lower()
                        if want and ekid == want and len(ek) == 32:
                            key = ek
                            print(f"[watcher] key MATCHED for KID {want}: {ek[:8]}...", flush=True)
                            break
                    if key: break
                if not key and attempt == 0:
                    print(f"[watcher] waiting for license exchange (KID {want})...", flush=True)
                if key or attempt == 29:
                    if not key:
                        print(f"[watcher] no entry matched KID {want} after 30s", flush=True)
                    break
                page.wait_for_timeout(1000)
            except Exception as e:
                print(f"[watcher] Failed to read service worker storage: {e}", flush=True)
                break
        else:
            print("[watcher] no service workers found to read keys from.", flush=True)
        # --- END NEW BLOCK ---
        if key: print(f"[watcher] key captured for KID {kid}", flush=True)
        else: print("[watcher] no key captured — play this lecture once in regular Chrome with WidevineProxy2 active, then re-run", flush=True)
        if not silent:
            print("[watcher] keeping browser open for 15s so I can inspect...", flush=True)
            page.wait_for_timeout(15000)
        browser.close()  # detach CDP; Chrome keeps running for next job
    return signed[0] if signed else None, kid, key

def download(ready, j, signed):
    import subprocess
    name = re.sub(r"[^\w\-. ()\[\]]+", "_", j.get("name", j["scheduleId"])).strip(" .")[:150] or "lecture"
    cmd = [CFG["nm3u8dl_path"], signed, "-H", "Accept: */*",
           "-H", "Origin: https://www.pw.live", "-H", "Referer: https://www.pw.live/",
           "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
           "--append-url-params"]
    if j.get("key") and j.get("kid"):
        cmd += ["--key", f"{j['kid']}:{j['key']}"]
        print(f"[watcher] decrypting with KEY {j['kid'][:8]}...:{j['key'][:8]}...", flush=True)
    cmd += ["-M", "format=mkv", "--auto-select", "--save-name", name, "--save-dir", str(OUT)]
    print(f"[watcher] downloading: {name}", flush=True)
    r = subprocess.run(cmd, cwd=CFG["nm3u8dl_workdir"])
    out = OUT / f"{name}.mkv"
    if r.returncode == 0 and out.exists():
        print(f"[watcher] DONE: {out} ({out.stat().st_size // 1024 // 1024} MB)", flush=True)
        ready.rename(ready.with_name(ready.stem + ".done.json"))
    else:
        print(f"[watcher] download FAILED (exit {r.returncode})", flush=True)
        ready.rename(ready.with_name(ready.stem + ".failed.json"))

def process(f):
    j = json.loads(f.read_text())
    print(f"Processing job {j['scheduleId']}: {j.get('name','')[:60]}", flush=True)
    try:
        signed, kid, key = capture(j)
        if not signed:
            print("FAILED: signed URL never arrived", flush=True)
            f.rename(f.with_name(f.stem + ".failed.json")); return
        if not key or not kid:
            print(f"NO KEY for KID {kid} - refusing to download (would be corrupt)", flush=True)
            print("To get the key: open the lecture in the watcher Chrome window,", flush=True)
            print("open wp2-custom popup, copy KID:KEY, then re-run.", flush=True)
            j.update({"signedUrl": signed, "kid": kid, "key": None,
                      "capturedAt": datetime.now(timezone.utc).isoformat()})
            f.write_text(json.dumps(j, indent=2))
            f.rename(f.with_name(f.stem + ".needkey.json")); return
        j.update({"signedUrl": signed, "kid": kid, "key": key,
                  "capturedAt": datetime.now(timezone.utc).isoformat()})
        f.write_text(json.dumps(j, indent=2))
        ready = f.with_name(f.stem + ".ready.json")
        f.rename(ready)
        print(f"[watcher] DONE — {ready.name} written", flush=True)
        download(ready, j, signed)
    except Exception: print(f"ERROR {f.name}:\n{traceback.format_exc()}", flush=True)

def main():
    print(f"Watching {JOBS}", flush=True)
    while True:
        for f in sorted(JOBS.glob("job_*.json")):
            if f.name.endswith((".done.json", ".failed.json", ".ready.json", ".needkey.json")): continue
            process(f)
        time.sleep(CFG.get("poll_seconds", 3))

if __name__ == "__main__": main()

