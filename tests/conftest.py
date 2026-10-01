import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeServer:
    """Serveur HTTP local programmable : enregistre les requêtes, renvoie une réponse JSON (ou un statut)."""

    def __init__(self):
        self.requests = []          # (path, headers, body bytes)
        self.response = {}          # dict JSON ou callable(path, body) -> dict
        self.status = 200
        self.delay_s = 0.0
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                server.requests.append((self.path, dict(self.headers), body))
                if server.delay_s:
                    time.sleep(server.delay_s)
                payload = server.response(self.path, body) if callable(server.response) else server.response
                data = json.dumps(payload).encode()
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = _reply
            do_GET = _reply

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def json_bodies(self):
        return [json.loads(b) for _, _, b in self.requests]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_server():
    s = FakeServer()
    yield s
    s.close()


@pytest.fixture
def dead_url():
    """URL d'un port local fermé (service down)."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"
