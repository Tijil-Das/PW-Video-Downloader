"""Central token store for the PW API Bearer token.

The Chrome extension pushes fresh tokens here via WebSocket whenever it
detects a token refresh (or on every capture, whichever comes first).
All backend modules should call get_token() instead of reading env vars
or config files directly.

Extension -> App message (handled by the future WebSocket bridge):
  { "type": "token_update", "token": "<jwt>", "source": "auto_refresh" }

On receipt, the bridge calls token_store.set_token(msg["token"],
msg["source"]). Token handshake is otherwise skipped (personal tool;
the bridge checks the Origin header instead).
"""
import base64
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_STORE_FILE = Path.home() / ".pw-downloader" / "token.json"
_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)

_token = None
_received_at = None


def set_token(token, source="extension"):
    """Called by the WebSocket bridge when the extension pushes a token."""
    global _token, _received_at
    with _LOCK:
        _token = token.strip()
        _received_at = datetime.now(timezone.utc).isoformat()
        _STORE_FILE.write_text(json.dumps({
            "token": _token, "received_at": _received_at, "source": source,
        }, indent=2))
    logger.info("token stored from %s", source)


def get_token(allow_env_fallback=True):
    """Most recent token: memory -> disk file -> PW_TOKEN env (if allowed)."""
    global _token, _received_at
    with _LOCK:
        if _token:
            return _token
        if _STORE_FILE.exists():
            try:
                data = json.loads(_STORE_FILE.read_text())
                _token = data.get("token")
                _received_at = data.get("received_at")
                if _token:
                    return _token
            except Exception:
                pass
        if allow_env_fallback:
            env_tok = os.environ.get("PW_TOKEN")
            if env_tok:
                _token = env_tok.strip()
                _received_at = "env"
                return _token
        return None


def token_age_seconds():
    """Seconds since the token was last set. None if unknown."""
    with _LOCK:
        if not _received_at or _received_at == "env":
            return None
        try:
            dt = datetime.fromisoformat(_received_at)
            return int((datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            return None


def is_token_expired():
    """Decode the JWT and check 'exp'. True if exp < now+60s."""
    tok = get_token()
    if not tok:
        return True
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = int(claims.get("exp", 0))
        return exp < (datetime.now(timezone.utc).timestamp() + 60)
    except Exception:
        return True
