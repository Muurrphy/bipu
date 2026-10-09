from __future__ import annotations
import json
import secrets
import urllib.parse
import threading
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, engine):
        self.engine = engine
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)

    def allowed_host(self, value):
        return value in {
            f"127.0.0.1:{self.server_port}",
            f"localhost:{self.server_port}",
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def body(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def trusted(self, post=False):
        if not self.server.allowed_host(self.headers.get("Host", "")):
            self.body(403, {"error": "Local host required"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }:
            self.body(403, {"error": "Same-origin required"})
            return False
        if post and not secrets.compare_digest(
            self.headers.get("X-Bipu-Token", ""), self.server.token
        ):
            self.body(403, {"error": "Missing local session token"})
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/":
                raw = (
                    files(__package__)
                    .joinpath("web.html")
                    .read_text()
                    .replace("__TOKEN__", self.server.token)
                    .encode()
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif path == "/api/state":
                self.body(200, self.server.engine.snapshot())
            elif path.startswith("/audio/"):
                ident = urllib.parse.unquote(path[7:])
                self.send_file(self.server.engine.assets.sound_file(ident))
            elif path.startswith("/video/"):
                ident = path[7:]
                p = self.server.engine.assets.videos.get(ident)
                if p is None:
                    raise ValueError("No reference video configured")
                self.send_file(p)
            else:
                self.body(404, {"error": "Not found"})
        except (ValueError, OSError):
            self.body(404, {"error": "Asset unavailable"})

    def send_file(self, path):
        size = path.stat().st_size
        start = 0
        end = size - 1
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
            if not match:
                self.body(416, {"error": "Invalid range"})
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else size - 1, size - 1)
            if start > end:
                self.body(416, {"error": "Invalid range"})
                return
        self.send_response(206 if range_header else 200)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(str(path))[0] or "application/octet-stream",
        )
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if range_header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def do_POST(self):
        if not self.trusted(True):
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                raise ValueError("Invalid body length")

            def invalid(v):
                raise ValueError("Non-finite JSON")

            data = json.loads(self.rfile.read(size), parse_constant=invalid)
            if not isinstance(data, dict):
                raise ValueError("Expected object")
            e = self.server.engine
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/start":
                e.start()
            elif path == "/api/stop":
                e.stop()
            elif path == "/api/message":
                e.message(data.get("text"))
            elif path == "/api/props":
                e.set_toys(data.get("ready"))
            elif path == "/api/score":
                e.start_score(data)
            elif path == "/api/shutdown":
                e.stop()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.body(404, {"error": "Unknown command"})
                return
            self.body(200, {"ok": True})
        except (ValueError, TypeError, KeyError) as error:
            self.body(400, {"error": str(error)})
        except Exception:
            self.body(500, {"error": "Request failed; inspect local runtime status"})
