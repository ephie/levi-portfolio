"""Serve the captured public website without making upstream network requests."""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["resources"]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested = urlsplit(self.path)
            if requested.path == "/mirror-sw.js":
                self.send_file(ROOT / "mirror-sw.js", "text/javascript")
            elif requested.path == "/__mirror__":
                url = parse_qs(requested.query).get("url", [""])[0]
                self.send_resource(url)
            elif requested.path.startswith("/__external__/"):
                self.send_resource(
                    "https://" + self.path.removeprefix("/__external__/")
                )
            else:
                self.send_file(ROOT / "index.html", "text/html; charset=utf-8")

        def send_resource(self, url):
            entry = entries.get(url)
            if entry is None:
                self.send_error(404, "Resource not captured: " + url)
                return
            file = (ROOT / entry["file"]).resolve()
            if not file.is_relative_to(ROOT):
                self.send_error(403)
                return
            self.send_file(file, entry["content_type"], rewrite=True)

        def send_file(self, path, content_type, rewrite=False):
            body = None
            if rewrite and any(
                kind in content_type for kind in ("json", "javascript", "css", "html")
            ):
                body = path.read_bytes()
                # Keep new tabs, PDF viewers and downloads inside the local
                # archive, where the original service worker cannot follow them.
                for host in ("media.base44.com", "base44.app", "img.youtube.com"):
                    body = body.replace(
                        f"https://{host}/".encode(),
                        (
                            f"http://{self.headers['Host']}"
                            f"/__external__/{host}/"
                        ).encode(),
                    )
            size = len(body) if body is not None else path.stat().st_size
            start, end = 0, size - 1
            status = 200
            if range_header := self.headers.get("Range"):
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                if not match or not any(match.groups()):
                    self.send_error(416, "Unsupported byte range")
                    return
                first, last = match.groups()
                start = int(first) if first else max(0, size - int(last))
                end = min(int(last), size - 1) if first and last else size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                if body is not None:
                    self.wfile.write(body[start:end + 1])
                    return
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.log_message("Client disconnected while reading %s", path.name)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Local archive: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
