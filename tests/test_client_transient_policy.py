"""Transient opt-in policy exercised at transport boundaries, without sockets."""
import contextlib
import unittest
from unittest.mock import MagicMock, patch

from api_client import ClientError, RelayClient


@contextlib.contextmanager
def transport(status=200, body=b'{"answers":[]}', headers=None):
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.getheader.side_effect = (headers if headers is not None else {
        'Cache-Control': 'no-store', 'X-Relay-Content-Deleted': 'true',
    }).get
    conn = MagicMock()
    conn.getresponse.return_value = response
    with patch('api_client.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), \
         patch('api_client.socket.socket'), patch('api_client.ssl.create_default_context'), \
         patch('api_client.http.client.HTTPConnection', return_value=conn), \
         patch('api_client.threading.Timer') as timer:
        yield conn, response, timer


def client(**kwargs):
    return RelayClient('https://example.invalid/v1', 'synthetic-client',
                       require_privacy=True, **kwargs)


class TransientPolicyTests(unittest.TestCase):
    def test_opt_in_504_leaves_client_available_for_explicit_next_attempt_only(self):
        with transport(status=504, headers={}) as (conn, response, _):
            relay = client(allow_transient_retry=True)
            with self.assertRaises(ClientError) as caught:
                relay.classify('synthetic', 'synthetic', {})
            self.assertEqual(caught.exception.code, 'http_504')
            self.assertIsNone(relay.privacy_failure)
            self.assertTrue(caught.exception.retryable)
            self.assertTrue(caught.exception.may_have_executed)
            self.assertFalse(caught.exception.admission_not_started)
            self.assertEqual(conn.request.call_count, 1)
            response.status = 200
            response.getheader.side_effect = {
                'Cache-Control': 'no-store', 'X-Relay-Content-Deleted': 'true',
            }.get
            self.assertEqual(relay.classify('synthetic', 'synthetic', {}), {'answers': []})
            self.assertEqual(conn.request.call_count, 2)

    def test_transient_http_matrix_is_opt_in_and_classification_only(self):
        for status in (502, 503, 504):
            for opt_in in (False, True):
                for catalog in (False, True):
                    with self.subTest(status=status, opt_in=opt_in, catalog=catalog), \
                         transport(status=status, headers={}) as (conn, _, _):
                        relay = client(allow_transient_retry=opt_in)
                        call = relay.models if catalog else lambda: relay.classify('m', 's', {})
                        with self.assertRaises(ClientError) as caught:
                            call()
                        retryable = opt_in and not catalog
                        self.assertEqual(caught.exception.retryable, retryable)
                        self.assertEqual(caught.exception.may_have_executed, retryable)
                        self.assertEqual(relay.privacy_failure, None if retryable else f'http_{status}')
                        self.assertEqual(conn.request.call_count, 1)
                        if not retryable:
                            with self.assertRaises(ClientError):
                                call()
                            self.assertEqual(conn.request.call_count, 1)

    def test_deadline_paths_and_transport_failure_have_the_same_policy(self):
        for mode in ('transport', 'expire', 'remaining', 'dns_remaining'):
            for opt_in, catalog in ((False, False), (True, False), (True, True)):
                with self.subTest(mode=mode, opt_in=opt_in, catalog=catalog), \
                     transport() as (conn, response, timer), \
                     patch('api_client.time.monotonic', return_value=0) as clock:
                    relay = client(timeout=1, allow_transient_retry=opt_in)
                    if mode == 'transport':
                        conn.getresponse.side_effect = OSError('synthetic')
                    elif mode == 'expire':
                        def interrupted():
                            timer.call_args.args[1]()
                            raise OSError('synthetic')
                        conn.getresponse.side_effect = interrupted
                    elif mode == 'remaining':
                        def late_read(*_):
                            clock.return_value = 2
                            return b'{}'
                        response.read.side_effect = late_read
                    else:
                        clock.side_effect = [0, 2]
                    call = relay.models if catalog else lambda: relay.classify('m', 's', {})
                    with self.assertRaises(ClientError) as caught:
                        call()
                    code = 'transport_error' if mode == 'transport' else 'timeout'
                    retryable = opt_in and not catalog
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(caught.exception.retryable, retryable)
                    self.assertEqual(caught.exception.may_have_executed, retryable)
                    self.assertEqual(relay.privacy_failure, None if retryable else code)
                    self.assertEqual(conn.request.call_count, 0 if mode == 'dns_remaining' else 1)

    def test_opt_in_never_bypasses_other_failures_or_existing_sticky_failure(self):
        cases = [(200, b'{}', {}, 'privacy_confirmation_missing'),
                 (401, b'{}', None, 'http_401'), (403, b'{}', None, 'http_403'),
                 (429, b'{"error":{"type":"capacity_busy"}}', None, 'http_429'),
                 (302, b'{}', {'Location': 'https://other.invalid/v1'}, 'http_302'),
                 (307, b'{}', None, 'http_307'), (500, b'{}', None, 'http_500'),
                 (200, b'{bad', None, 'invalid_json'), (200, b'[]', None, 'invalid_schema'),
                 (200, b'{"error":null}', None, 'api_error')]
        for status, body, headers, code in cases:
            with self.subTest(code=code), transport(status, body, headers) as (conn, _, _):
                relay = client(allow_transient_retry=True)
                with self.assertRaises(ClientError) as caught:
                    relay.classify('m', 's', {})
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(caught.exception.retryable)
                self.assertFalse(caught.exception.may_have_executed)
                self.assertEqual(conn.request.call_count, 1)
                # No opt-in or destination change clears an existing terminal failure.
                relay.privacy_failure = code
                relay._parts = relay._parts._replace(netloc='other.invalid')
                with self.assertRaises(ClientError) as blocked:
                    relay.classify('m', 's', {})
                self.assertFalse(blocked.exception.retryable)
                self.assertEqual(relay.privacy_failure, code)
                self.assertEqual(conn.request.call_count, 1)

    def test_proven_capacity_busy_preserves_not_started_contract_with_opt_in(self):
        body = b'{"error":{"type":"capacity_busy","admission":"not_started",' \
               b'"limit_scope":"concurrency","retry_after":1}}'
        with transport(429, body) as (conn, _, _):
            relay = client(allow_transient_retry=True)
            with self.assertRaises(ClientError) as caught:
                relay.classify('m', 's', {})
            self.assertEqual(caught.exception.code, 'capacity_busy')
            self.assertTrue(caught.exception.admission_not_started)
            self.assertEqual(caught.exception.retry_after, 1)
            self.assertFalse(caught.exception.retryable)
            self.assertFalse(caught.exception.may_have_executed)
            self.assertIsNone(relay.privacy_failure)
            self.assertEqual(conn.request.call_count, 1)
