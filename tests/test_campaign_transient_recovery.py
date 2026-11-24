"""Explicit at-least-once recovery; synthetic enums only, no network/history."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api_client import ClientError
from private_checkpoint import Journal


class TransientRecoveryTests(unittest.TestCase):
    def journal(self, root, resume=False):
        return Journal(root.resolve() / 'journal', resume, {'contract': 'unchanged'},
                       ['one', 'two', 'three'], [{'yes': 'yes'}] * 3)

    def test_fixture_canonicalizes_system_temp_before_strict_journal(self):
        canonical = Path('/synthetic/canonical-temp')
        with patch.object(Path, 'resolve', return_value=canonical), patch(__name__ + '.Journal') as journal:
            self.journal(Path('/synthetic/temp-alias'))
        self.assertEqual(journal.call_args.args[0], canonical / 'journal')

    def test_504_retries_same_segment_and_commits_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self.journal(Path(tmp))
            calls = []
            try:
                j.enable_retry(max_attempts=3, backoff=0)
                def operation():
                    # Every POST has durable write-ahead, including retries.
                    durable = json.loads((j.path / 'state.json').read_text())
                    self.assertEqual(durable['segments'][0]['status'], 'unknown')
                    calls.append(1)
                    if len(calls) == 1:
                        raise ClientError('http_504')
                    return 'yes'
                self.assertEqual(j.decision(operation, {'yes': 'yes'}), 'yes')
                self.assertEqual(len(calls), 2)
                self.assertEqual(j.data['segments'][0]['status'], 'ok')
                self.assertEqual(j.recovery_stats()['retries'], 1)
                self.assertEqual(j.recovery_stats()['errors']['http_504'], 1)
                self.assertFalse(j.paused)
            finally:
                j.close()

    def test_old_uncertainty_requires_explicit_recovery_and_preserves_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); j = self.journal(root)
            try:
                j.decision(lambda: 'yes', {'yes': 'yes'})
                def broken():
                    raise ClientError('http_504')
                j.decision(broken, {'yes': 'yes'})
                prefix = dict(j.data['segments'][0])
            finally:
                j.close()
            j = self.journal(root, True)
            try:
                j.enable_retry(max_attempts=3, backoff=0)
                self.assertTrue(j.paused, 'do not silently replay legacy unknown')
                j.enable_retry(max_attempts=3, backoff=0, recover_uncertain=True)
                self.assertFalse(j.paused)
                self.assertEqual(j.decision(lambda: self.fail('confirmed replay'), {'yes': 'yes'}), 'yes')
                self.assertEqual(j.decision(lambda: 'yes', {'yes': 'yes'}), 'yes')
                self.assertEqual(j.decision(lambda: 'yes', {'yes': 'yes'}), 'yes')
                self.assertEqual(j.data['segments'][0], prefix)
                self.assertEqual(j.recovery_stats()['uncertain_replays'], 1)
            finally:
                j.close()

    def test_exhausted_transient_does_not_block_remaining_then_resume_repairs_only_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); j = self.journal(root)
            calls = []
            def broken():
                calls.append(1)
                raise ClientError('http_503')
            try:
                j.enable_retry(max_attempts=2, backoff=0)
                self.assertEqual(j.decision(lambda: 'yes', {'yes': 'yes'}), 'yes')
                self.assertIsNone(j.decision(broken, {'yes': 'yes'}))
                self.assertEqual(len(calls), 2)
                self.assertFalse(j.paused)
                self.assertEqual(j.decision(lambda: 'yes', {'yes': 'yes'}), 'yes')
                self.assertEqual([r['status'] for r in j.data['segments']], ['ok', 'unknown', 'ok'])
            finally:
                j.close()
            j = self.journal(root, True)
            try:
                j.enable_retry(max_attempts=2, backoff=0)
                for index in range(3):
                    def complete(i=index):
                        self.assertEqual(i, 1, 'only gap may execute')
                        return 'yes'
                    self.assertEqual(j.decision(complete, {'yes': 'yes'}), 'yes')
            finally:
                j.close()

    def test_auth_privacy_and_invalid_response_do_not_retry_or_sweep(self):
        for code in ('http_401', 'http_403', 'privacy_confirmation_missing', 'invalid_json', 'http_429'):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                j = self.journal(Path(tmp)); calls = []
                try:
                    j.enable_retry(max_attempts=3, backoff=0)
                    def broken():
                        calls.append(1)
                        raise ClientError(code)
                    self.assertIsNone(j.decision(broken, {'yes': 'yes'}))
                    self.assertIsNone(j.decision(lambda: self.fail('unsafe sweep'), {'yes': 'yes'}))
                    self.assertEqual(len(calls), 1)
                    self.assertTrue(j.paused)
                finally:
                    j.close()

    def test_retry_write_failure_propagates_before_second_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self.journal(Path(tmp)); calls = []
            try:
                j.enable_retry(max_attempts=3, backoff=0)
                original = j.save
                def save():
                    if calls:
                        raise OSError('synthetic disk failure')
                    return original()
                def broken():
                    calls.append(1)
                    raise ClientError('http_504')
                with patch.object(j, 'save', side_effect=save):
                    with self.assertRaises(OSError):
                        j.decision(broken, {'yes': 'yes'})
                self.assertEqual(len(calls), 1)
            finally:
                j.close()

    def test_backoff_grows_and_capacity_hint_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = self.journal(Path(tmp)); calls = []
            try:
                j.enable_retry(max_attempts=4, backoff=2)
                def operation():
                    calls.append(1)
                    if len(calls) < 4:
                        raise ClientError('http_504')
                    return 'yes'
                with patch('private_checkpoint.time.sleep') as sleep:
                    self.assertEqual(j.decision(operation, {'yes': 'yes'}), 'yes')
                    self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4, 8])
            finally:
                j.close()


if __name__ == '__main__':
    unittest.main()
