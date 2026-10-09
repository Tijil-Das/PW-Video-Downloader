"""WebSocket bridge: extension <-> desktop app. Binds 127.0.0.1 ONLY.

Handshake: Origin MUST be chrome-extension://<EXTENSION_ID> else 1008.
Token handshake SKIPPED for now (personal tool; Origin check is enough).
Keepalive: ping every 20s, drop socket if no pong within 30s.
Runs on its own asyncio thread; pywebview keeps its own loop.
"""
import asyncio
import json
import threading
import time


class BridgeServer:
    def __init__(self, config, downloader, on_event=None):
        self.config = config
        self.downloader = downloader
        self.on_event = on_event or (lambda *a: None)
        self.clients = set()
        self.thread = None
        self.loop = None
        self._server = None
        self._running = False
        self.last_pong = {}

    def port(self):
        return int(self.config.get("ws_port", 9777))

    def is_running(self):
        return self._running

    def _allowed_origin(self, origin):
        if not origin:
            return False
        if not origin.startswith("chrome-extension://"):
            return False
        want = str(self.config.get("extension_id", "") or "").strip().lower()
        if not want:
            return True  # ID unknown yet: accept any extension origin
        return origin.lower() == f"chrome-extension://{want}"

    async def _handler(self, ws):
        import websockets
        origin = ""
        try:
            # websockets>=14: headers live on ws.request.headers (old: ws.request_headers)
            req = getattr(ws, "request", None)
            hdrs = getattr(req, "headers", None) if req is not None else None
            if hdrs is not None:
                origin = hdrs.get("Origin", "") or hdrs.get("origin", "") or ""
            else:
                origin = (ws.request_headers.get("Origin", "") or "")
        except Exception:
            pass
        if not self._allowed_origin(origin):
            await ws.close(code=1008, reason="bad origin")
            return
        self.clients.add(ws)
        self.last_pong[id(ws)] = time.time()
        try:
            await ws.send(json.dumps({"type": "welcome"}))
        except Exception:
            pass
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                t = msg.get("type")
                if t == "hello":
                    try:
                        await ws.send(json.dumps({"type": "welcome"}))
                    except Exception:
                        pass
                elif t == "pong":
                    self.last_pong[id(ws)] = time.time()
                elif t == "job":
                    # Phase 4.1 fast-path: refuse unconfigured jobs BEFORE
                    # queueing so the card shows the Settings error at once.
                    _cfg = self.downloader.config or {}
                    if not (_cfg.get("base_storage_path") or "").strip() or \
                       not (_cfg.get("batch_name") or "").strip():
                        try:
                            await ws.send(json.dumps({
                                "type": "error", "jobId": msg.get("jobId") or msg.get("scheduleId"),
                                "tabId": msg.get("tabId"),
                                "code": "no_config",
                                "message": "Set base storage path and batch name in the app Settings first"}))
                        except Exception:
                            pass
                        continue
                    job_id = self.downloader.submit(msg)
                    try:
                        self.downloader.set_job_tab(job_id, msg.get("tabId"))
                    except Exception:
                        pass
                    self.on_event("job", job_id)
                    try:
                        await ws.send(json.dumps({"type": "ack", "jobId": job_id}))
                    except Exception:
                        pass
                    # BUGFIX: extension may have reconnected between submit
                    # and this ack (MV3 suspends the worker); re-push the
                    # job's CURRENT stage so the card never sticks on queued.
                    try:
                        cur = next((j for j in self.downloader.list_jobs()
                                    if j.get("jobId") == job_id), None)
                        if cur and cur.get("stage") != "queued":
                            await ws.send(json.dumps({"type": "status", **{
                                k: cur.get(k) for k in
                                ("jobId", "stage", "pct", "detail")}}))
                    except Exception:
                        pass
                elif t == "cancel":
                    self.downloader.cancel(msg.get("jobId"))
                elif t == "token_update":
                    # Central token push: extension -> backend store.
                    try:
                        from token_store import set_token
                        tok = (msg.get("token") or "").strip()
                        if tok:
                            set_token(tok, msg.get("source") or "extension-ws")
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            self.clients.discard(ws)
            self.last_pong.pop(id(ws), None)

    async def _ping_loop(self):
        while self._running:
            await asyncio.sleep(20)
            dead = [ws for ws, ts in list(self.last_pong.items())]
            now = time.time()
            for ws in list(self.clients):
                if now - self.last_pong.get(id(ws), now) > 30:
                    try:
                        await ws.close(code=1008, reason="pong timeout")
                    except Exception:
                        pass
                    continue
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    pass

    async def _serve(self):
        import websockets
        self._server = await websockets.serve(
            self._handler, "127.0.0.1", self.port())
        asyncio.create_task(self._ping_loop())
        await self._server.wait_closed()

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        except Exception:
            pass

    def start(self):
        if self._running:
            return True
        self._running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self._running = False
        try:
            if self._server and self.loop:
                self.loop.call_soon_threadsafe(self._server.close)
        except Exception:
            pass
        return True

    def broadcast(self, payload):
        loop, clients = self.loop, list(self.clients)
        if not loop or not clients:
            return
        data = json.dumps(payload)

        async def _send():
            for ws in clients:  # snapshot: set may change mid-send
                try:
                    await ws.send(data)
                except Exception:
                    pass
        try:
            # Fire-and-forget: never block the worker on a slow socket.
            # React polls list_jobs(); WS is best-effort live push only.
            asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception:
            pass
