"""PW watcher part 1/2: config, watch URL, KID parse."""
import json, re, time, traceback, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text())
PROFILE_DIR = r"C:\Users\tijil\pw-chrome-profile"
_CDM_VERIFIED = False  # CDM can't uninstall mid-run; verify once per watcher process
JOBS = Path(CFG["jobs_dir"]); OUT = Path(CFG["output_dir"])
OUT.mkdir(parents=True, exist_ok=True); JOBS.mkdir(parents=True, exist_ok=True)

def watch_url(j):
    # FIX: batchSlug param MUST be the human slug (e.g. mission-100-jee-2027-225226),
    # NOT the hex batchId. PW redirects to homepage on a wrong slug.
    slug = j.get("batchSlug") or j["batchId"]
    s = j["scheduleId"]
    return (f"https://www.pw.live/watch/?batchSlug={slug}&batchSubjectId={j['batchSubjectId']}"
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

def _fresh_profile_guard(prof):
    """Official branded-Chrome profile: NEVER back up/rename (holds logins).
    Just refuse a foreign Chromium-owned dir; otherwise pass through."""
    try:
        prof = Path(prof)
        off = str(prof).lower()
        marker = prof / ".pw-chromium-owner"
        ours = "playwright-chromium-1243"
        if prof.exists():
            if marker.exists():
                try:
                    if marker.read_text().strip() == ours:
                        return True
                except Exception:
                    pass
            lv = prof / "Last Version"
            if lv.exists():
                try:
                    print(f"[watcher] profile Last Version: {lv.read_text()[:40]!r}", flush=True)
                except Exception:
                    pass
            bak = Path(str(prof) + ".bak")
            import shutil
            if bak.exists():
                shutil.rmtree(bak, ignore_errors=True)
            try:
                prof.rename(bak)
                print("[watcher] profile version mismatch, starting fresh", flush=True)
            except Exception as e:
                print(f"[watcher] profile backup failed: {e}", flush=True)
                return False
        try:
            prof.mkdir(parents=True, exist_ok=True)
            marker.write_text(ours)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[watcher] profile guard failed: {e}", flush=True)
        return False


def _ctx_of(browser):
    """launch_persistent_context returns a BrowserContext (NOT a Browser):
    it has .pages/.new_page directly and NO .contexts. Normalize both."""
    try:
        ctxs = getattr(browser, "contexts", None)
        if ctxs:
            return ctxs[0]
    except Exception:
        pass
def _ctx_of(browser):
    """launch_persistent_context returns a BrowserContext (NOT a Browser):
    it has .pages/.new_page directly and NO .contexts. Normalize both."""
    try:
        ctxs = getattr(browser, "contexts", None)
        if ctxs:
            return ctxs[0]
    except Exception:
        pass
    return browser


def _page_of(ctx):
    try:
        pages = getattr(ctx, "pages", None) or []
        if pages:
            return pages[0]
    except Exception:
        pass
    return ctx.new_page()


def _service_workers_of(ctx):
    try:
        return list(getattr(ctx, "service_workers", None) or [])
    except Exception:
        return []


def _needs_login(page):
    """Heuristic: expired tokens -> PW bounces to login/OTP instead of watch."""
    """Heuristic: expired tokens -> PW bounces to login/OTP instead of watch."""
    try:
        url = (page.url or "").lower()
        if any(k in url for k in ("/login", "signin", "/auth", "otp", "/account/login")):
            return True
        txt = ""
        try:
            txt = (page.evaluate("() => document.body ? document.body.innerText.slice(0,1200) : ''") or "").lower()
        except Exception:
            txt = ""
        keys = ("log in to continue", "login to continue", "please login",
                "session expired", "verify otp", "enter otp", "resend otp")
        return any(k in txt for k in keys)
    except Exception:
        return False


def _relaunch_visible_for_login(tm, p, ctx, wp2_src, prof, login_wait_ms, watch_fn):
    """Expired tokens -> PW shows login/OTP. Close ctx, open VISIBLE Thorium
    for manual login (same profile), wait, close, relaunch silent ctx."""
    print("[watcher] login needed (tokens expired?) - opening VISIBLE window for manual login", flush=True)
    try:
        ctx.close()
    except Exception:
        pass
    try:
        ctx_v, _ = tm.launch_context(p, str(prof), wp2_src, headless=False)
        page_v = _page_of(ctx_v)
        try:
            page_v.goto(watch_fn, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"[watcher] visible goto failed: {e}", flush=True)
        print("[watcher] VISIBLE login window open - log in to PW, then wait...", flush=True)
        try:
            page_v.wait_for_function("() => location.href.includes('/watch/')", timeout=login_wait_ms)
        except Exception:
            pass
        try:
            ok = "/watch/" in (page_v.url or "") and not _needs_login(page_v)
        except Exception:
            ok = False
        print(f"[watcher] login {'OK' if ok else 'NOT detected - continuing anyway'}", flush=True)
    finally:
        try:
            ctx_v.close()
        except Exception:
            pass
    ctx_s, wp2_s = tm.launch_context(p, str(prof), wp2_src, headless=False)
    return ctx_s, wp2_s


def capture(job):
    """Thorium (Widevine built-in) via ThoriumManager: auto-download, WP2
    pre-injected, Playwright-driven. No manual steps except PW login."""
    import sys as _sys
    from playwright.sync_api import sync_playwright
    global _CDM_VERIFIED
    signed, login_wait = [], CFG.get("login_wait_seconds", 300) * 1000
    prof = Path(CFG["chrome_profile_dir"])
    thorium_dir = CFG.get("thorium_install_dir", str(ROOT / ".." / "thorium"))
    wp2_src = str(Path(CFG.get("widevineproxy2_path", "") or "").resolve())
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop" / "backend"))
    from thorium_manager import ThoriumManager
    tm = ThoriumManager(thorium_dir)
    with sync_playwright() as p:
        try:
            ctx, wp2_id = tm.launch_context(p, str(prof), wp2_src, headless=False)
        except Exception as e:
            print(f"[watcher] LAUNCH FAILED: {e}", flush=True)
            return None, None, None
        if not wp2_id:
            print("[watcher] ABORT: WP2 not loaded. Cannot capture Widevine key.", flush=True)
            try:
                ctx.close()
            except Exception:
                pass
            return None, None, None
        browser = ctx  # persistent ctx IS the browser handle
        silent = bool(CFG.get("silent", True))
        print(f"[watcher] Thorium running ({'SILENT' if silent else 'VISIBLE'})", flush=True)
        # stealth: hide automation flags so PW's devtool-detector doesn't blank the player
        try:
            ctx.add_init_script("""() => {
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = window.chrome || { runtime: {} };
                const origOpen = window.open;
            }""")
        except Exception as e: print(f"[watcher] stealth script skipped: {e}", flush=True)
        page = _page_of(ctx)
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
        # SPEED-ONLY: verify once per process; skip on later jobs when already 4.10.x.
        if _CDM_VERIFIED:
            print("[watcher] CDM pre-check skipped (already verified 4.10.x this process)", flush=True)
        else:
            print("[watcher] checking Widevine CDM...", flush=True)
            try:
                chk = ctx.new_page()
                chk.goto("chrome://components/")
                chk.wait_for_timeout(1000)
                # wait until at least 2 component rows render (Widevine loads async)
                try: chk.wait_for_function("() => document.body && document.body.innerText.split('Version:').length > 2", timeout=3000)
                except Exception: pass
                wv_version = chk.evaluate("""() => {
                    const txt = document.body ? document.body.innerText : '';
                    const i = txt.toLowerCase().indexOf('widevine');
                    if (i < 0) return 'Widevine row MISSING; visible rows: ' + txt.slice(0,200);
                    return txt.slice(Math.max(0,i-60), i+160);
                }""")
                print(f"[watcher] Widevine CDM version: {str(wv_version)[:300]}", flush=True)
                if "4.10." in str(wv_version):
                    _CDM_VERIFIED = True
                    print("[watcher] CDM verified 4.10.x — future jobs skip CDM checks", flush=True)
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
                        chk.wait_for_timeout(3000)
                        chk.reload()
                        chk.wait_for_timeout(1000)
                        wv2 = chk.evaluate("() => document.body ? document.body.innerText.slice(0,400) : 'no-body'")
                        print(f"[watcher] CDM after update attempt: {str(wv2)[:300]}", flush=True)
                        if "4.10." in str(wv2):
                            _CDM_VERIFIED = True
                    except Exception as e2: print(f"[watcher] CDM update click failed: {e2}", flush=True)
                chk.close()
            except Exception as e: print(f"[watcher] CDM pre-check skipped: {e}", flush=True)
        print(f"[watcher] Chrome running ({'SILENT' if silent else 'VISIBLE'})", flush=True)
        if not silent:
            try: page.bring_to_front()
            except Exception: pass
        # SIGNED-URL SNIFF: register BEFORE navigation (player fetches MPD on load,
        # before any play click — the old post-detection registration missed it).
        # FIX 3: tight sniff on RESPONSE (content-type checked) + crash guard.
        try:
            def _sniff_ok(r):
                try:
                    u = r.url or ""
                    if "/master.mpd" not in u:
                        return False
                    if "Signature=" not in u and "URLPrefix=" not in u:
                        return False
                    ct = ""
                    try:
                        ct = (r.headers.get("content-type", "") or "").lower()
                    except Exception:
                        ct = ""
                    if ct and ("dash" not in ct and "mpegurl" not in ct):
                        return False
                    return True
                except Exception:
                    return False
            def _sniff(r):
                try:
                    if _sniff_ok(r) and not signed:
                        signed.append(r.url)
                except Exception:
                    pass
            page.on("response", _sniff)
        except Exception as e:
            print(f"[watcher] sniff setup failed: {e} - aborting", flush=True)
            return None, None, None
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
            for w in _service_workers_of(ctx):
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
                # WP2 is pre-installed in the profile (branded Chrome ignores
                # --load-extension), so a miss here is timing — the worker scan
                # below retries with refreshes before giving up.
                print("[watcher] MAIN-world probe inconclusive — WP2 pre-installed, continuing (no abort)", flush=True)
        except Exception as e:
            print(f"[watcher] WP2 pre-flight failed: {e}", flush=True)
            return None, None, None
        page.goto(watch_url(job), wait_until="domcontentloaded")
        # FIX 1b: abort if PW bounced us off /watch/ (wrong slug -> homepage).
        try:
            if "/watch/" not in (page.url or ""):
                # Expired tokens look like a redirect too — offer visible login
                # instead of dying when the page is actually asking to log in.
                try:
                    if _needs_login(page):
                        ctx, wp2_id = _relaunch_visible_for_login(
                            tm, p, ctx, wp2_src, prof, login_wait, watch_url(job))
                        browser = ctx
                        page = _page_of(ctx)
                        try:
                            page.goto(watch_url(job), wait_until="domcontentloaded", timeout=45000)
                        except Exception as e:
                            print(f"[watcher] post-login goto failed: {e}", flush=True)
                            return None, None, None
                    else:
                        print(f"[watcher] URL redirected to {page.url} — aborting", flush=True)
                        return None, None, None
                except Exception:
                    print(f"[watcher] URL redirected to {page.url} — aborting", flush=True)
                    return None, None, None
        except Exception:
            pass
        # Silent page already on /watch/ but showing login text: same flow.
        try:
            if "/watch/" in (page.url or "") and _needs_login(page):
                ctx, wp2_id = _relaunch_visible_for_login(
                    tm, p, ctx, wp2_src, prof, login_wait, watch_url(job))
                browser = ctx
                page = _page_of(ctx)
                try:
                    page.goto(watch_url(job), wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    print(f"[watcher] post-login goto failed: {e}", flush=True)
                    return None, None, None
        except Exception:
            pass
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
                page.wait_for_timeout(500)
        # FIX: reload the page if the EME probe raced navigation (context destroyed).
        # The sniff hooks survive; the signed URL fires on the fresh load.
        # CDM component version via chrome://components
        # SPEED-ONLY: skip duplicate check when pre-check already verified 4.10.x.
        if _CDM_VERIFIED:
            print("[watcher] CDM version check skipped (already verified 4.10.x this process)", flush=True)
        else:
            try:
                cp = ctx.new_page()
                cp.goto("chrome://components", wait_until="domcontentloaded")
                cp.wait_for_timeout(1500)
                ver = cp.evaluate("() => document.documentElement.innerText.match(/Widevine[^\\n]*\\n[^\\n]*/)?.[0] || 'not found'")
                print(f"[watcher] Widevine CDM version: {ver}", flush=True)
                if "4.10." in str(ver):
                    _CDM_VERIFIED = True
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
        page.wait_for_timeout(300)
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
        # SPEED-ONLY: event-driven — poll for <video> every 500ms, max 5s (same order/decisions).
        try:
            for _settle in range(10):
                has_video = page.evaluate("() => !!document.querySelector('video')")
                if has_video or signed:
                    break
                page.wait_for_timeout(500)
        except Exception: pass
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
                page.wait_for_timeout(500)
        except Exception as e: print(f"[watcher] play loop skipped: {e}", flush=True)
        try:
            # SPEED-ONLY: bounded 60x500ms poll (same 30s window as key-poll; was unbounded).
            for _sniff in range(60):
                if signed:
                    break
                page.wait_for_timeout(500)
        except Exception as e:
            print(f"[watcher] page died during sniff: {e}", flush=True)
            if not signed:
                print("[watcher] no signed URL captured - page crashed", flush=True)
                browser.close()
                return None, kid_from_mpd(job.get("mpdUrl", "")), None
        # FIX 3b: guard empty list BEFORE touching signed[0].
        if not signed:
            print("[watcher] no signed URL captured", flush=True)
            return None, None, None
        print("[watcher] signed URL captured", flush=True)
        kid = kid_from_mpd(signed[0]) or kid_from_mpd(job.get("mpdUrl", ""))
        print(f"[watcher] DEBUG KID: {kid}", flush=True)
        key = None
        # --- NEW: Read keys directly from the WP2 service worker ---
        print("[watcher] reading keys from service worker storage...", flush=True)
        key = None
        _sws = _service_workers_of(ctx)
        if _sws:
            sw = None
            for w in _service_workers_of(ctx):  # prefer the WP2 worker
                if wp2_id and wp2_id in w.url: sw = w; break
            sw = sw or _sws[0]
        # WP2 needs time for the license exchange; poll up to 30s for the KID match.
        # SPEED-ONLY: 60x500ms = same 30s window, 2x faster hit.
        want = (kid or "").replace("-", "").lower()
        for attempt in range(60):
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
                if key or attempt == 59:
                    if not key:
                        print(f"[watcher] no entry matched KID {want} after 30s", flush=True)
                    break
                page.wait_for_timeout(500)
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
    cmd += ["-M", "format=mkv", "--auto-select", "--thread-count", "16", "-mt",
            "--save-name", name, "--save-dir", str(OUT)]
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

