"""Run the unittest suite without opening network fixtures (even loopback).

HTTP-fixture tests are explicitly skipped, not counted as validated transport.
The ordinary unittest command remains the canonical unrestricted suite.
"""
from pathlib import Path
import socket
import socketserver
import sys
import unittest
from unittest.mock import patch


def forbidden(*_args, **_kwargs):
    raise unittest.SkipTest('network fixture disabled: no network authorized')


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with patch.object(socketserver.TCPServer, '__init__', forbidden), \
            patch.object(socket.socket, 'connect', forbidden), \
            patch.object(socket.socket, 'bind', forbidden), \
            patch.object(socket, 'getaddrinfo', forbidden):
        suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
