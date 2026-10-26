"""QueueForge Nexus local development server.
Serves the frontend console on http://localhost:5173 and proxies /api/* to the backend on http://127.0.0.1:8000.
"""
from __future__ import annotations

import http.server
import os
import urllib.error
import urllib.request

PORT = 5173
API_BACKEND = "http://127.0.0.1:8000"
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend"))


class DevProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def do_proxy(self):
        url = f"{API_BACKEND}{self.path}"
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length", "connection")
        }
        length = int(self.headers.get("content-length", 0))
        data = self.rfile.read(length) if length > 0 else None
        req = urllib.request.Request(url, data=data, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
                content = resp.read()
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ("transfer-encoding", "content-length"):
                    self.send_header(k, v)
            content = e.read()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            msg = f'{{"error": "Backend unavailable ({str(e)})"}}\n'.encode("utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        if self.path.startswith("/api"):
            return self.do_proxy()
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api"):
            return self.do_proxy()
        self.send_error(405)

    def do_PATCH(self):
        if self.path.startswith("/api"):
            return self.do_proxy()
        self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith("/api"):
            return self.do_proxy()
        self.send_error(405)

    def do_OPTIONS(self):
        if self.path.startswith("/api"):
            return self.do_proxy()
        self.send_response(204)
        self.end_headers()


def run(port: int = PORT):
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), DevProxyHandler)
    print(f"QueueForge Console serving at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
