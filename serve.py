#!/usr/bin/env python3
"""Static file server with HTTP Range support (needed for HTML5 audio seeking)."""
from __future__ import annotations

import argparse
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeRequestHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    extensions_map = {
        **getattr(SimpleHTTPRequestHandler, "extensions_map", {}),
        ".opus": "audio/ogg",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".srt": "application/x-subrip; charset=utf-8",
    }

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=3600")
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        if not os.path.isfile(path):
            self.send_error(404, "File not found")
            return None

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        fs = os.fstat(f.fileno())
        size = fs.st_size
        ctype = self.guess_type(path)
        range_header = self.headers.get("Range")

        if not range_header:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            return f

        m = RANGE_RE.fullmatch(range_header.strip())
        if not m:
            f.close()
            self.send_error(400, "Invalid Range")
            return None

        start_s, end_s = m.groups()
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else size - 1
        if end_s == "" and start_s == "":
            f.close()
            self.send_error(400, "Invalid Range")
            return None
        if start_s == "" and end_s:
            # suffix: bytes=-N
            length = int(end_s)
            if length <= 0:
                f.close()
                self.send_error(400, "Invalid Range")
                return None
            start = max(0, size - length)
            end = size - 1

        if start >= size or end >= size or start > end:
            f.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        length = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        f.seek(start)
        return _RangedFile(f, length)

    def copyfile(self, source, outputfile):
        if isinstance(source, _RangedFile):
            remaining = source.remaining
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
            source.close()
            return
        super().copyfile(source, outputfile)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


class _RangedFile:
    def __init__(self, fileobj, remaining: int):
        self._f = fileobj
        self.remaining = remaining

    def read(self, n: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        if n < 0 or n > self.remaining:
            n = self.remaining
        data = self._f.read(n)
        self.remaining -= len(data)
        return data

    def close(self) -> None:
        self._f.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--dir", default=os.getcwd())
    args = parser.parse_args()
    os.chdir(args.dir)
    httpd = ThreadingHTTPServer((args.bind, args.port), RangeRequestHandler)
    print(f"Serving {os.getcwd()} on http://{args.bind}:{args.port}/ (Range enabled)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)


if __name__ == "__main__":
    main()
