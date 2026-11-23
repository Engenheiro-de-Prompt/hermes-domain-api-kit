"""Portable relay client, without configuration or filesystem access."""


import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit


def _destination(value):
    try:
        if (not isinstance(value, str) or not value.isascii()
                or any(ord(c) <= 32 or ord(c) == 127 for c in value)
                or any(c in value for c in '\\?#')):
            raise ValueError
        if re.search(r'%(?![0-9a-fA-F]{2})|%(?:0[0-9a-fA-F]|1[0-9a-fA-F]|20|7[fF]|5[cC])', value):
            raise ValueError
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in ('http', 'https') or not host
                or '@' in parts.netloc or '%' in parts.netloc
                or parts.netloc.endswith(':') or parts.port == 0):
            raise ValueError
        if parts.scheme == 'http' and host != '127.0.0.1':
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.split('.')
            if (not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                        for label in labels) or len(host) > 253
                    or all(re.fullmatch(r'(?:[0-9]+|0[xX][0-9a-fA-F]+)', label)
                           for label in labels)):
                raise ValueError
        return parts
    except (ValueError, TypeError, AttributeError):
        raise ClientError('invalid_url') from None


def _reject_constant(_value):
    raise ValueError


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class ClientError(Exception):
    """Safe client failure."""

    def __init__(self, code):
        self.code = code
        self.admission_not_started = False
        self.retry_after = None
        super().__init__(code)


def privacy_destination(value):
    parts = _destination(value)
    if ('%' in parts.path or not parts.path.rstrip('/').endswith('/v1')
            or any(segment.lower() == 'host' for segment in parts.path.split('/'))):
        raise ClientError('privacy_endpoint_required')
    return parts


def _privacy_headers(getheader, *, remote):
    cache = (getheader('Cache-Control') or '').lower().split(',')
    if ('no-store' not in {part.strip() for part in cache}
            or remote and (getheader('X-Relay-Content-Deleted') or '').strip().lower() != 'true'):
        raise ClientError('privacy_confirmation_missing')


class RelayClient:
    def __init__(self, base_url, key, timeout=145, *, require_privacy=False, keep_alive=None):
        self._parts = privacy_destination(base_url) if require_privacy else _destination(base_url)
        self.require_privacy = require_privacy
        self.privacy_failure = None
        if (not isinstance(key, str) or not key or not key.isascii()
                or any(ord(c) <= 32 or ord(c) == 127 for c in key)
                or key.startswith('lr_agent')):
            raise ClientError('invalid_key')
        if (type(timeout) not in (int, float) or timeout <= 0
                or timeout > threading.TIMEOUT_MAX or not math.isfinite(timeout)):
            raise ClientError('invalid_timeout')
        if keep_alive is not None and (type(keep_alive) is not int or keep_alive < -1):
            raise ClientError('invalid_keep_alive')
        self._keep_alive = keep_alive
        self._key = key
        self._timeout = timeout

    def models(self) -> dict:
        return self._request('GET', '/models')

    def classify(self, model, state, questions) -> dict:
        import json

        try:
            payload = {'model': model, 'state': state, 'questions': questions}
            # Omission lets the server own campaign retention; explicit 0 is not omitted.
            if self._keep_alive is not None:
                payload['keep_alive'] = self._keep_alive
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise ClientError('invalid_payload') from None
        if len(body) > 1024 * 1024:
            raise ClientError('payload_too_large')
        return self._request('POST', '/classifications', body)

    def _request(self, method, route, body=None):
        if self.privacy_failure is not None:
            raise ClientError(self.privacy_failure)
        deadline = time.monotonic() + self._timeout
        parts = self._parts
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        conn = http.client.HTTPConnection(parts.hostname, port, timeout=self._timeout)
        timer = None
        response = None
        expired = threading.Event()

        def remaining():
            left = deadline - time.monotonic()
            if left <= 0:
                if self.require_privacy:
                    self.privacy_failure = 'timeout'
                raise ClientError('timeout')
            return left

        try:
            # getaddrinfo is the only blocking operation stdlib cannot cancel.
            # Its elapsed time still consumes the deadline once it returns.
            addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
            last_error = OSError()
            for family, socktype, proto, _, address in addresses:
                sock = socket.socket(family, socktype, proto)
                try:
                    sock.settimeout(remaining())
                    sock.connect(address)
                except OSError as exc:
                    sock.close()
                    last_error = exc
                except BaseException:
                    sock.close()
                    raise
                else:
                    conn.sock = sock
                    break
            else:
                raise last_error
            if parts.scheme == 'https':
                context = ssl.create_default_context()
                conn.sock.settimeout(remaining())
                conn.sock = context.wrap_socket(conn.sock, server_hostname=parts.hostname)
            transport = conn.sock

            def expire():
                expired.set()
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            transport.settimeout(remaining())
            timer = threading.Timer(remaining(), expire)
            timer.daemon = True
            timer.start()
            conn.request(method, parts.path.rstrip('/') + route, body=body, headers={
                'Authorization': 'Bearer ' + self._key,
                'X-Relay-Timeout': str(min(120, self._timeout)),
                'Content-Type': 'application/json',
                'Cache-Control': 'no-store',
                'Pragma': 'no-cache',
            })
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                # Only an authenticated HTTPS response with privacy confirmation
                # and the exact pre-admission contract permits a future resume.
                if response.status == 429 and self.require_privacy and parts.scheme == 'https':
                    try:
                        _privacy_headers(response.getheader, remote=True)
                        raw = response.read(65537)
                        remaining()
                        result = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                                            parse_constant=_reject_constant, parse_float=_finite_float) if len(raw) <= 65536 else None
                        proof = result.get('error') if isinstance(result, dict) else None
                        if (isinstance(proof, dict) and proof.get('type') == 'capacity_busy'
                                and proof.get('admission') == 'not_started'
                                and proof.get('limit_scope') == 'concurrency'
                                and type(proof.get('retry_after')) is int
                                and 1 <= proof['retry_after'] <= 60):
                            error = ClientError('capacity_busy')
                            error.admission_not_started = True
                            error.retry_after = proof['retry_after']
                            raise error
                    except ClientError as error:
                        if error.admission_not_started:
                            raise
                    except (ValueError, UnicodeError, RecursionError):
                        pass
                if self.require_privacy:
                    self.privacy_failure = f'http_{response.status}'
                raise ClientError(f'http_{response.status}')
            if self.require_privacy:
                try:
                    _privacy_headers(response.getheader, remote=parts.scheme == 'https')
                except ClientError:
                    self.privacy_failure = 'privacy_confirmation_missing'
                    raise
            data = response.read(2 * 1024 * 1024 + 1)
            remaining()
            if len(data) > 2 * 1024 * 1024:
                raise ClientError('response_too_large')
            try:
                result = json.loads(data.decode('utf-8'),
                                    parse_constant=_reject_constant,
                                    parse_float=_finite_float,
                                    object_pairs_hook=_unique_object)
            except (ValueError, UnicodeError, RecursionError):
                raise ClientError('invalid_json') from None
            if not isinstance(result, dict):
                raise ClientError('invalid_schema')
            if 'error' in result:
                raise ClientError('api_error')
            return result
        except (OSError, http.client.HTTPException):
            code = 'timeout' if expired.is_set() or time.monotonic() >= deadline else 'transport_error'
            if self.require_privacy:
                self.privacy_failure = code
            raise ClientError(code) from None
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            if response is not None:
                response.close()
            conn.close()
