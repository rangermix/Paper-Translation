"""Dependency-free HTTP host for the DESIGN prototype. Never implements ingestion or translation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
ROOT = Path(__file__).resolve().parents[1]
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
    def do_HEAD(self):
        return self._serve(head_only=True)
    def do_GET(self):
        return self._serve(head_only=False)
    def _serve(self, head_only=False):
        path = unquote(urlsplit(self.path).path)
        if path == '/health/live':
            value = json.dumps({'status':'ok','mode':'design-prototype','backend_translation':False}).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(value))); self.end_headers();
            if not head_only: self.wfile.write(value)
            return
        if any(p in ('..',) for p in path.replace('\\','/').split('/')) or '\x00' in path or '\\' in path:
            self.send_error(400, 'Invalid path'); return
        candidate = ROOT / path.lstrip('/')
        try:
            candidate.resolve().relative_to(ROOT)
        except ValueError:
            self.send_error(400, 'Invalid path'); return
        if any(part.startswith('.') for part in Path(path).parts if part not in ('/', '.')):
            self.send_error(404); return
        if head_only: super().do_HEAD()
        else: super().do_GET()
    def do_POST(self):
        self.send_error(405, 'Design prototype: no upload or model API')
    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    def list_directory(self, path):
        self.send_error(404, 'Directory listing disabled'); return None
    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        super().end_headers()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8080)
    args=p.parse_args()
    print(f'Design prototype at http://{args.host}:{args.port}; no production backend.',flush=True)
    ThreadingHTTPServer((args.host,args.port), Handler).serve_forever()
if __name__=='__main__':main()
