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
                    job_id = self.downloader.submit(msg)
                    self.on_event("job", job_id)
                    try:
                        await ws.send(json.dumps({"type": "ack", "jobId": job_id}))
                    except Exception:
                        pass
                elif t == "cancel":
                    self.downloader.cancel(msg.get("jobId"))
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
        if not self.loop or not self.clients:
            return
        data = json.dumps(payload)

        async def _send():
            for ws in list(self.clients):
                try:
                    await ws.send(data)
                except Exception:
                    pass
        try:
            asyncio.run_coroutine_threadsafe(_send(), self.loop)
        except Exception:
            pass
