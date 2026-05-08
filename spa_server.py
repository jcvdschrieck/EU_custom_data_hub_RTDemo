"""Minimal SPA-aware static file server.

Serves files from the given directory. Any path that does not resolve to an
existing file is answered with index.html so client-side routers work on hard
refresh.

Usage:
    python spa_server.py <directory> <port>
"""
import sys
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer


class SPAHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        result = super().translate_path(path)
        if not os.path.exists(result) or os.path.isdir(result):
            return os.path.join(self.directory, "index.html")
        return result

    def log_message(self, fmt, *args):
        sys.stdout.write(f"{self.address_string()} - {fmt % args}\n")
        sys.stdout.flush()


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    os.chdir(directory)
    handler = lambda *a, **kw: SPAHandler(*a, directory=directory, **kw)
    server = HTTPServer(("0.0.0.0", port), handler)
    print(f"Serving SPA from {directory} on http://0.0.0.0:{port}")
    sys.stdout.flush()
    server.serve_forever()
