"""Serve this replay-only frontend using Python's standard library."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ReplayHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(404)

    def do_POST(self):
        self.send_error(405, 'Recorded replay has no write or inference endpoints')

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8892)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    handler = partial(ReplayHandler, directory=str(root))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'C2 recorded Evidence Studio: http://127.0.0.1:{args.port}/', flush=True)
        print('Replay only. No model calls, database connections or memory writes.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
