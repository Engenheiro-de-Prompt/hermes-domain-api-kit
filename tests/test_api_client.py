"""Offline contract tests: only synthetic loopback HTTP fixtures."""
import json
import os
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from api_client import ClientError, RelayClient

KEY = 'synthetic-client-token'


@contextmanager
def fixture(status=200, body=b'{"models":[]}', headers=None, slow=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            payload = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            requests.append((self.command, self.path, dict(self.headers), payload))
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                if slow:
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.04)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class ClientTests(unittest.TestCase):
    def test_poisoned_proxy_environment_is_ignored_for_both_methods(self):
        with fixture(status=500) as (proxy, intercepted):
            with fixture(body=b'{"data":[]}') as (destination, requests):
                env={name:proxy for name in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')}
                env.update({'no_proxy':'','NO_PROXY':''})
                with patch.dict(os.environ,env):
                    client=RelayClient(destination,KEY,timeout=3)
                    self.assertEqual(client.models(),{'data':[]})
                    self.assertEqual(client.classify('synthetic',{'text':'example'},[]),{'data':[]})
            self.assertEqual(len(requests),2)
        self.assertEqual(len(intercepted),0,'proxy must not receive credentials')

    def test_invalid_destinations_fail_before_network_without_echo(self):
        invalid = [
            '', 'https://', 'http://example.test', 'http://localhost',
            'https://user:secret@example.test', 'https://example.test?',
            'https://example.test#', 'https://example.test:0',
            'https://example.test:', 'https://example.test:65536',
            'https://example.test\\evil', 'https://example.test/\nsecret',
            'https://example.test/ secret', 'https://127.1', 'https://2130706433',
            'https://0177.0.0.1', 'https://0x7f000001', 'https://a..test',
            'https://example.test.', 'https://%65xample.test',
            'https://-bad.test', 'https://[fe80::1%25eth0]',
            'https://éxample.test', 'https://example.test/%0dsecret',
        ]
        with patch('socket.getaddrinfo', side_effect=AssertionError('network forbidden')) as dns:
            for index, url in enumerate(invalid):
                with self.subTest(case=index):
                    with self.assertRaises(ClientError) as caught:
                        RelayClient(url, KEY)
                    self.assertEqual(caught.exception.code, 'invalid_url')
                    self.assertEqual(str(caught.exception), 'invalid_url')
            dns.assert_not_called()

    def test_credentials_are_validated_in_memory_and_repr_is_opaque(self):
        for index, key in enumerate(['', 'lr_agent_test', 'lr_agent', 'has space',
                                     'tab\there', 'line\nbreak', 'é', 'a\x7f', None]):
            with self.subTest(case=index):
                with self.assertRaises(ClientError) as caught:
                    RelayClient('https://relay.example', key)
                self.assertEqual(caught.exception.code, 'invalid_key')
        client = RelayClient('https://relay.example/private', KEY)
        self.assertNotIn(KEY, repr(client))
        self.assertNotIn('relay.example', repr(client))

    def test_classify_posts_the_public_contract(self):
        with fixture(body=b'{"answers":[]}') as (url, requests):
            client = RelayClient(url, KEY, timeout=4)
            self.assertTrue(callable(getattr(client, 'classify', None)), 'classify missing')
            self.assertEqual(client.classify('model-a', {'text': 'olá'}, ['q1']), {'answers': []})
        self.assertEqual(len(requests), 1)
        method, path, headers, body = requests[0]
        self.assertEqual((method, path), ('POST', '/classifications'))
        self.assertEqual(headers['Authorization'], 'Bearer ' + KEY)
        self.assertEqual(headers['X-Relay-Timeout'], '4')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(json.loads(body.decode('utf-8')), {
            'model': 'model-a', 'state': {'text': 'olá'}, 'questions': ['q1'], 'keep_alive': 0,
        })

    def test_non_success_http_is_static_and_never_retried(self):
        for status in (302, 307, 400, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                with fixture(status=status, body=(KEY + ' private server detail').encode(),
                             headers={'Location': '/second-route'}) as (url, requests):
                    with self.assertRaises(ClientError) as caught:
                        RelayClient(url, KEY).models()
                self.assertEqual(caught.exception.code, f'http_{status}')
                self.assertEqual(str(caught.exception), f'http_{status}')
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0][1], '/models')

    def test_response_requires_strict_utf8_json_object_without_error(self):
        cases = [(b'{bad private detail', 'invalid_json'), (b'{"x":"\xff"}', 'invalid_json'),
                 (b'{"x":NaN}', 'invalid_json'), (b'{"x":Infinity}', 'invalid_json'),
                 (b'{"x":-Infinity}', 'invalid_json'), (b'{"x":1e999}', 'invalid_json'),
                 (b'{"x":1,"x":2}', 'invalid_json'),
                 (b'{"x":{"a":1,"a":2}}', 'invalid_json'),
                 (b'[]', 'invalid_schema'), (b'null', 'invalid_schema'),
                 (b'{"error":null}', 'api_error'), (b'{"error":"private"}', 'api_error')]
        for index, (body, code) in enumerate(cases):
            with self.subTest(case=index):
                with fixture(body=body) as (url, requests):
                    with self.assertRaises(ClientError) as caught:
                        RelayClient(url, KEY).models()
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(str(caught.exception), code)
                self.assertEqual(len(requests), 1)

    def test_payload_is_strict_and_bounded_in_utf8_bytes_before_network(self):
        with fixture() as (url, requests):
            client = RelayClient(url, KEY)
            for index, state in enumerate([float('nan'), float('inf'), object(), '\ud800']):
                with self.subTest(case=index):
                    with self.assertRaises(ClientError) as caught:
                        client.classify('m', state, [])
                    self.assertEqual(caught.exception.code, 'invalid_payload')
            with self.assertRaises(ClientError) as caught:
                client.classify('m', 'é' * (512 * 1024), [])
            self.assertEqual(caught.exception.code, 'payload_too_large')
            self.assertEqual(requests, [])
            overhead = len(json.dumps({'model': 'm', 'state': '', 'questions': [],
                                      'keep_alive': 0}, ensure_ascii=False).encode())
            client.classify('m', 'a' * (1024 * 1024 - overhead), [])
            self.assertEqual(len(requests[0][3]), 1024 * 1024)

    def test_response_limit_is_exactly_two_mib(self):
        limit = 2 * 1024 * 1024
        body = b'{"data":"' + b'a' * (limit - len(b'{"data":""}')) + b'"}'
        with fixture(body=body) as (url, requests):
            self.assertEqual(len(RelayClient(url, KEY).models()['data']), limit - 11)
        with fixture(body=body + b' ') as (url, requests):
            with self.assertRaises(ClientError) as caught:
                RelayClient(url, KEY).models()
            self.assertEqual(caught.exception.code, 'response_too_large')
            self.assertEqual(len(requests), 1)

    def test_slow_body_has_an_absolute_deadline_without_replay(self):
        with fixture(body=b'{"data":"' + b'a' * 40 + b'"}', slow=True) as (url, requests):
            started = time.monotonic()
            with self.assertRaises(ClientError) as caught:
                RelayClient(url, KEY, timeout=0.15).models()
            elapsed = time.monotonic() - started
            self.assertEqual(caught.exception.code, 'timeout')
            self.assertLess(elapsed, 0.65)
            self.assertEqual(len(requests), 1)

    def test_timeout_must_be_a_finite_positive_number(self):
        for index, timeout in enumerate([0, -1, float('nan'), float('inf'), True, '2', None]):
            with self.subTest(case=index):
                with self.assertRaises(ClientError) as caught:
                    RelayClient('https://relay.example', KEY, timeout=timeout)
                self.assertEqual(caught.exception.code, 'invalid_timeout')

    def test_models_real_http_shape(self):
        with fixture() as (url, requests):
            result = RelayClient(url + '/v1/', KEY).models()
        self.assertEqual(result, {'models': []})
        self.assertEqual(len(requests), 1)
        method, path, headers, body = requests[0]
        self.assertEqual((method, path, body), ('GET', '/v1/models', b''))
        self.assertEqual(headers['Authorization'], 'Bearer ' + KEY)
        self.assertEqual(headers['X-Relay-Timeout'], '120')


if __name__ == '__main__':
    unittest.main()
