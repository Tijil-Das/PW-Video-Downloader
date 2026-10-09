"""Headless self-test: Api + WS server + job flow WITHOUT window/Chrome.

Run: python desktop/backend/selftest_headless.py   (must print SELFTEST PASS)
"""
import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from server import BridgeServer
import downloader as dl_mod


class FakeEngine:
    CFG = {}
    OUT = BACKEND / "selftest_out"

    @staticmethod
    def capture(job):
        time.sleep(0.3)
        return ("https://cdn/signed.mpd", "aabbcc", "001122")


def fake_run(cmd, cwd=None):
    class R:
        returncode = 0
    name = cmd[cmd.index("--save-name") + 1]
    d = Path(cmd[cmd.index("--save-dir") + 1])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.mkv").write_bytes(b"x" * 100)
    return R()


def main():
    import subprocess
    from config import load_config
    real = load_config()
    subprocess.run = fake_run
    orig_engine = dl_mod._engine
    dl_mod._engine = FakeEngine
    FakeEngine.CFG = {
        "chromium_executable": real["chromium_executable"],
        "widevineproxy2_path": real["widevineproxy2_path"],
        "nm3u8dl_path": real["nm3u8dl_path"],
        "nm3u8dl_workdir": real["nm3u8dl_workdir"],
    }
    try:
        from downloader import Downloader
        from main import Api
        events = []
        api = Api.__new__(Api)  # no window, no auto-start: wire manually
        api._config = {"ws_port": 19877, "extension_id": "",
                       "output_dir": str(BACKEND / "selftest_out")}
        api._window = None
        cfg = {"output_dir": str(BACKEND / "selftest_out"),
               "base_storage_path": str(BACKEND / "selftest_out"),
               "batch_name": "Selftest", "batch_slug": "", "batch_id": "",
               "thorium_install_dir": str(BACKEND / "selftest_thorium")}
        # Fake Thorium exe so the engine pre-check passes without downloading.
        import thorium_manager as tm_mod
        (BACKEND / "selftest_thorium").mkdir(parents=True, exist_ok=True)
        (BACKEND / "selftest_thorium" / "thorium.exe").write_bytes(b"x")
        api._downloader = Downloader(cfg, api._on_status.__get__(api, Api))
        api._server = srv = BridgeServer(api._config, api._downloader)
        import folder_resolver as fr_mod
        orig_resolve = fr_mod.resolve_folder_path
        fr_mod.resolve_folder_path = lambda job: {
            "subject_name": "Selftest Subject", "chapter_name": "Selftest Chapter",
            "lecture_date": "2026-01-01", "lecture_date_iso": "2026-01-01T00:00:00.000Z",
            "thumbnail_url": job.get("thumbnailUrl") or None,
            "relative_path": "Selftest Subject/Selftest Chapter/Demo.mkv",
            "subject_slug": "", "chapter_slug": "", "chapter_id": "",
            "error": None}
        orig_emit = api._downloader._emit
        # record events AND run the real bridge path
        def rec_emit(job_id, stage, pct=0, detail=""):
            events.append((job_id, stage, pct, detail))
            return orig_emit(job_id, stage, pct, detail)
        api._downloader._emit = rec_emit
        assert srv.start()
        time.sleep(1.0)

        async def t():
            import websockets
            async with websockets.connect(
                    "ws://127.0.0.1:19877",
                    origin="chrome-extension://selftest") as ws:
                hello = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert hello["type"] == "welcome", hello
                await ws.send(json.dumps({"type": "job", "jobId": "j1",
                                          "scheduleId": "s1", "name": "Demo",
                                          "batchId": "b1", "batchSlug": "b1",
                                          "batchSubjectId": "sub1"}))
                got_ack, got_done, stages = False, None, []
                # Linear recv with deadline: pong replies inline, never
                # starve the reader with a background task.
                deadline = time.time() + 25
                while time.time() < deadline:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    except TimeoutError:
                        continue
                    if m.get("type") == "ack":
                        got_ack = True
                    elif m.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                    elif m.get("type") in ("status", "done", "error"):
                        stages.append(m.get("stage", m.get("type")))
                        if m.get("type") == "done":
                            got_done = m
                            break
                        if m.get("type") == "error":
                            raise AssertionError(f"job errored: {m}")
                assert got_ack, "no ack"
                assert got_done, f"no done, stages={stages}"
                return got_done
        done = asyncio.run(t())
        srv.stop()
        assert events, "no status events"
        print("SELFTEST PASS", done.get("path"), [s for _, s, _, _ in events])
    finally:
        dl_mod._engine = orig_engine
        try:
            import folder_resolver as _fr
            _fr.resolve_folder_path = orig_resolve
        except Exception:
            pass


if __name__ == "__main__":
    main()
