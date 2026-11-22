import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from api_client import RelayClient, ClientError, _privacy_headers


class PrivacyClientTests(unittest.TestCase):
    def test_remote_missing_deletion_blocks(self):
        for h in ({'Cache-Control': 'no-store'}, {'Cache-Control': 'no-store', 'X-Relay-Content-Deleted': 'false'}):
            with self.assertRaisesRegex(ClientError, '^privacy_confirmation_missing$'):
                _privacy_headers(h.get, remote=True)

    def test_confirmed_remote_and_no_store_token(self):
        _privacy_headers({'Cache-Control': 'private, no-store', 'X-Relay-Content-Deleted': 'true'}.get, remote=True)
        for cache in ('', 'public', 'no-store-ish'):
            with self.assertRaises(ClientError):
                _privacy_headers({'Cache-Control': cache, 'X-Relay-Content-Deleted': 'true'}.get, remote=True)

    def test_idle_or_non_v1_rejected(self):
        for url in ('https://example.invalid/api/public/host/jobs', 'https://example.invalid/host/v1', 'https://example.invalid/%68ost/v1', 'https://example.invalid/Host/v1', 'https://example.invalid/not-api'):
            with self.subTest(url=url), self.assertRaisesRegex(ClientError, '^privacy_endpoint_required$'):
                RelayClient(url, 'synthetic', require_privacy=True)

    def test_http_integration_cache_and_legacy_compatibility(self):
        captured = []
        headers = {}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                captured.append(dict(self.headers))
                self.send_response(200)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(json.dumps({'data': []}).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_port) + '/v1'
            self.assertEqual(RelayClient(url, 'synthetic').models(), {'data': []})
            with self.assertRaisesRegex(ClientError, '^privacy_confirmation_missing$'):
                RelayClient(url, 'synthetic', require_privacy=True).models()
            headers['Cache-Control'] = 'no-store'
            self.assertEqual(RelayClient(url, 'synthetic', require_privacy=True).models(), {'data': []})
            self.assertEqual(captured[-1]['Cache-Control'], 'no-store')
            self.assertEqual(captured[-1]['Pragma'], 'no-cache')
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
