"""Job queue: single worker wraps the EXISTING watch.py engine unchanged.

Phase 4: resolve subject/chapter via folder_resolver, save into the
Storage library layout, download thumbnails (no auth), index lectures.
done carries the final path.
"""
import importlib.util
import queue
import re
import subprocess
import threading
import traceback
import uuid
from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parents[2] / "downloader" / "watch.py"

_spec = importlib.util.spec_from_file_location("pw_watch_engine", ENGINE_PATH)
_engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_engine)

STAGES = ("queued", "signing", "downloading", "decrypting", "done", "error")
NO_CONFIG_MSG = "Set base storage path and batch name in the app Settings first"

class Downloader:
    def __init__(self, config, on_status=None):
        self.config = config
        self.on_status = on_status or (lambda *a: None)
        self.q = queue.Queue()
        self.jobs = {}
        self.cancelled = set()
        self.lock = threading.Lock()
        self.out_dir = Path(config.get("output_dir", _engine.OUT and str(_engine.OUT)))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()

    def _emit(self, job_id, stage, pct=0, detail=""):
        with self.lock:
            rec = self.jobs.get(job_id, {})
            rec.update({"jobId": job_id, "stage": stage, "pct": pct, "detail": detail})
            self.jobs[job_id] = rec
            snapshot = dict(rec)
        try:
            # Live routing: carry the capture tab so the extension targets
            # the right card (broadcast in main.py forwards full snapshot).
            self.on_status(job_id, stage, pct, detail)
        except Exception:
            pass
        return snapshot

    def set_job_tab(self, job_id, tab_id):
        try:
            with self.lock:
                if job_id in self.jobs and tab_id is not None:
                    self.jobs[job_id]["tabId"] = tab_id
        except Exception:
            pass
        return True

    def submit(self, job):
        job = dict(job or {})
        job_id = str(job.get("jobId") or job.get("scheduleId") or uuid.uuid4().hex[:8])
        with self.lock:
            self.jobs[job_id] = {
                "jobId": job_id,
                "scheduleId": job.get("scheduleId", job_id),
                "name": job.get("name", job_id),
                "mpdUrl": job.get("mpdUrl", ""),
                "batchId": job.get("batchId", ""),
                "batchSubjectId": job.get("batchSubjectId", ""),
                "thumbnailUrl": job.get("thumbnailUrl", ""),
                "tabId": job.get("tabId"),
                "stage": "queued", "pct": 0, "detail": "queued", "path": None,
                "_job": job, "_kind": "lecture",
            }
        self.q.put(job_id)
        # BUGFIX: emit AFTER queueing so the worker's signing update can't
        # overtake queued on a reconnecting socket (card stuck forever).
        self._emit(job_id, "queued", 0, "queued")
        return job_id

    def submit_dpps(self, subject_slug, chapter_slug, subject_name, chapter_name):
        job_id = f"dpp-{uuid.uuid4().hex[:8]}"
        with self.lock:
            self.jobs[job_id] = {
                "jobId": job_id, "stage": "queued", "pct": 0, "detail": "queued",
                "name": f"DPPs: {chapter_name}", "path": None,
                "_kind": "dpps",
                "_job": {"subject_slug": subject_slug, "chapter_slug": chapter_slug,
                         "subject_name": subject_name, "chapter_name": chapter_name},
            }
        self.q.put(job_id)
        self._emit(job_id, "queued", 0, "queued")
        return job_id

    def cancel(self, job_id):
        self.cancelled.add(str(job_id))
        self._emit(str(job_id), "error", 0, "cancelled")
        return True

    def list_jobs(self):
        with self.lock:
            return [{k: v for k, v in rec.items() if not k.startswith("_")}
                    for rec in self.jobs.values()]

    def _worker(self):
        while True:
            job_id = self.q.get()
            try:
                if job_id in self.cancelled:
                    continue
                with self.lock:
                    kind = self.jobs.get(job_id, {}).get("_kind", "lecture")
                if kind == "dpps":
                    self._process_dpps(job_id)
                else:
                    self._process(job_id)
            except Exception:
                traceback.print_exc()
                self._emit(job_id, "error", 0, "worker crash")
            finally:
                self.q.task_done()

    def _process_dpps(self, job_id):
        with self.lock:
            job = dict(self.jobs[job_id].get("_job", {}))
        base = (self.config.get("base_storage_path") or "").strip()
        batch = (self.config.get("batch_name") or "").strip()
        if not base or not batch:
            self._emit(job_id, "error", 0, NO_CONFIG_MSG)
            return
        from storage import Storage
        from library_manager import LibraryIndex
        from dpp_fetcher import list_dpps, download_dpp
        st = Storage(base, batch)
        paths = st.ensure_chapter_folders(job["subject_name"], job["chapter_name"])
        idx = LibraryIndex(st)
        res = list_dpps(self.config.get("batch_slug"), job["subject_slug"], job["chapter_slug"])
        if res.get("error"):
            self._emit(job_id, "error", 0, res["error"][:200])
            return
        dpps, n = res["dpps"], max(len(res["dpps"]), 1)
        from datetime import datetime, timezone
        for i, dpp in enumerate(dpps, 1):
            if job_id in self.cancelled:
                return
            self._emit(job_id, "downloading", int(i / n * 100), f"{i}/{len(dpps)} downloaded")
            fname = f"{dpp.get('date') + ' - ' if dpp.get('date') else ''}{dpp.get('name')}"
            r = download_dpp(dpp.get("url"), paths["dpp_dir"], filename=fname, index=i)
            if r.get("valid"):
                idx.upsert_dpp(job["subject_name"], job["chapter_name"],
                               {"dpp_name": dpp.get("name"), "date": dpp.get("date"),
                                "date_iso": dpp.get("date_iso"), "url": dpp.get("url")},
                               {"meta": {"batch_slug": self.config.get("batch_slug"),
                                         "batch_id": self.config.get("batch_id")},
                                "file_name": Path(r["path"]).name,
                                "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "size_bytes": r.get("size")})
        with self.lock:
            self.jobs[job_id]["path"] = paths["dpp_dir"]
        self._emit(job_id, "done", 100, f"{len(dpps)}/{len(dpps)} saved to {paths['dpp_dir']}")

    def _process(self, job_id):
        with self.lock:
            job = dict(self.jobs[job_id].get("_job", {}))
        if job_id in self.cancelled:
            return
        # Phase 4.1: Settings gate — refuse before touching Chrome.
        base = (self.config.get("base_storage_path") or "").strip()
        batch_name = (self.config.get("batch_name") or "").strip()
        if not base or not batch_name:
            self._emit(job_id, "error", 0, NO_CONFIG_MSG)
            with self.lock:
                self.jobs[job_id]["no_config"] = True
            return
        # Engine pre-checks WITHOUT launching the browser: surface config
        # errors on the card instead of silently dying in the worker.
        # Thorium path: only verify wp2 + downloader tooling here. NEVER
        # gate on the Thorium exe — capture() auto-downloads it on first run,
        # so refusing here would deadlock ("start a capture to download" while
        # refusing every capture).
        wp2 = Path(_engine.CFG.get("widevineproxy2_path") or "")
        if not wp2.exists():
            self._emit(job_id, "error", 0, f"wp2-custom missing at {wp2}")
            return
        # Phase 4.2: resolve subject/chapter/slugs BEFORE capture.
        from folder_resolver import resolve_folder_path
        info = resolve_folder_path(job)
        if info.get("error"):
            self._emit(job_id, "error", 0, f"resolve failed: {info['error']}"[:200])
            return
        subject = info.get("subject_name") or "_Unsorted"
        chapter = info.get("chapter_name") or "_Unsorted"
        # Phase 4.3: chapter folders.
        from storage import Storage
        from library_manager import LibraryIndex
        st = Storage(base, batch_name)
        paths = st.ensure_chapter_folders(subject, chapter)
        idx = LibraryIndex(st)
        # --- signing: existing Playwright capture (signed URL + WP2 key) ---
        self._emit(job_id, "signing", 5, "signing URL + reading key")
        try:
            signed, kid, key = _engine.capture(job)
        except Exception as e:
            self._emit(job_id, "error", 0, f"capture crashed: {str(e)[:120]}")
            return
        if job_id in self.cancelled:
            return
        if not signed:
            self._emit(job_id, "error", 0, "signed URL never arrived")
            return
        if not key or not kid:
            # Same guard as watch.py: refuse corrupt download without key.
            self._emit(job_id, "error", 0, f"NO KEY for KID {kid}")
            return
        # --- downloading/decrypting: same N_m3u8DL-RE flags as watch.py ---
        # Phase 4.4: final file lands at video_path(lecture_name).
        self._emit(job_id, "downloading", 20, "downloading segments")
        lecture_name = job.get("name", job.get("scheduleId", job_id))
        name = re.sub(r"[^\w\-. ()\[\]]+", "_", lecture_name).strip(" .")[:150] or "lecture"
        video_file = Path(paths["video_path"](lecture_name)).name
        cfg = _engine.CFG
        cmd = [cfg["nm3u8dl_path"], signed, "-H", "Accept: */*",
               "-H", "Origin: https://www.pw.live", "-H", "Referer: https://www.pw.live/",
               "-H", ("User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"),
               "--append-url-params", "--key", f"{kid}:{key}",
               "-M", "format=mkv", "--auto-select", "--thread-count", "16", "-mt",
               "--save-name", Path(video_file).stem, "--save-dir", paths["video_dir"]]
        self._emit(job_id, "decrypting", 70, f"decrypting {str(kid)[:8]}...")
        r = subprocess.run(cmd, cwd=cfg["nm3u8dl_workdir"])
        out = Path(paths["video_dir"]) / video_file
        if r.returncode == 0 and out.exists():
            # Phase 4.5: thumbnail PNG, NO auth (static PW URL).
            thumb_file = Path(paths["thumb_path"](lecture_name)).name
            thumb_url = info.get("thumbnail_url")
            if thumb_url:
                try:
                    import requests
                    tr = requests.get(thumb_url, timeout=30)
                    if tr.ok and tr.content:
                        Path(paths["thumb_dir"], thumb_file).write_bytes(tr.content)
                except Exception:
                    pass
            # Phase 4.6: index the lecture.
            from datetime import datetime, timezone
            size = out.stat().st_size
            idx.upsert_lecture(
                subject, chapter,
                {"schedule_id": job.get("scheduleId", job_id),
                 "name": lecture_name,
                 "date": info.get("lecture_date"),
                 "date_iso": info.get("lecture_date_iso"),
                 "thumbnail_url": thumb_url,
                 "kid": kid, "key": key},
                {"meta": {"batch_slug": self.config.get("batch_slug"),
                          "batch_id": self.config.get("batch_id"),
                          "subject_slug": info.get("subject_slug"),
                          "chapter_slug": info.get("chapter_slug"),
                          "chapter_id": info.get("chapter_id")},
                 "video_file": video_file, "thumb_file": thumb_file,
                 "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "size_bytes": size})
            with self.lock:
                self.jobs[job_id]["path"] = str(out)
            self._emit(job_id, "done", 100, f"saved ({size // 1024 // 1024} MB)")
        else:
            self._emit(job_id, "error", 0, f"download FAILED (exit {r.returncode})")
