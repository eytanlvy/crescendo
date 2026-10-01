"""Appels HTTP aux services locaux (stdlib urllib) avec erreurs explicites."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request


class ServiceError(Exception):
    """Service local injoignable, trop lent ou en erreur. `service` : "whisper" ou "ollama"."""

    def __init__(self, service: str, message: str, kind: str = "error"):
        super().__init__(f"{service} : {message}")
        self.service = service
        self.kind = kind  # "down", "timeout" ou "error"


def post(service: str, url: str, body: bytes, content_type: str, timeout_s: float) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise ServiceError(service, f"HTTP {e.code} sur {url} : {detail}") from None
    except (TimeoutError, socket.timeout):
        raise ServiceError(service, f"délai dépassé ({timeout_s:g} s) sur {url}", "timeout") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise ServiceError(service, f"délai dépassé ({timeout_s:g} s) sur {url}", "timeout") from None
        raise ServiceError(service, f"injoignable sur {url} ({e.reason})", "down") from None
    except ConnectionError as e:
        raise ServiceError(service, f"injoignable sur {url} ({e})", "down") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ServiceError(service, f"réponse non JSON : {raw[:200]!r}") from None
    if isinstance(data, dict) and data.get("error"):
        raise ServiceError(service, str(data["error"]))
    return data


def post_json(service: str, url: str, payload: dict, timeout_s: float) -> dict:
    return post(service, url, json.dumps(payload).encode(), "application/json", timeout_s)
