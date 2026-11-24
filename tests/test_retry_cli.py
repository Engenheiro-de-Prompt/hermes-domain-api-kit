"""Synthetic CLI recovery of the SAME campaign, preserving confirmed results."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api_client import ClientError
import test_private_resume as resume_fixtures


class RetryCliTests(unittest.TestCase):
    def setUp(self):
        self.helper = resume_fixtures.PrivateResumeTests()

    def test_resume_old_504_keeps_confirmed_prefix_and_finishes_all_rubrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.helper.source(root); work = root / 'exports'
            first = self.helper.client()
            original = first.classify
            def interrupted(*args):
                if first.calls == 2:
                    first.calls += 1
                    raise ClientError('http_504')
                return original(*args)
            first.classify = interrupted
            self.assertEqual(self.helper.invoke(source, work, first)[0], 1)
            state = root / 'exports.checkpoint' / 'state.json'
            before = json.loads(state.read_text())
            known = [dict(r) for r in before['segments'] if r['status'] == 'ok']
            self.assertEqual(len(known), 2)
            second = self.helper.client()
            rc, out, err = self.helper.invoke(source, work, second,
                ['--resume', '--retry-transient', '--recover-uncertain', '--retry-backoff', '0'])
            self.assertEqual(rc, 0, err.getvalue())
            report = json.loads((work / 'report.json').read_text())
            self.assertTrue(report['complete'])
            self.assertIsNone(report['pause_reason'])
            self.assertEqual(second.calls, report['planned_classifier_calls'] - len(known))
            self.assertEqual(report['confirmed_classifier_calls'], report['planned_classifier_calls'])
            self.assertEqual(report['recovery']['uncertain_replays'], 1)
            self.assertEqual(report['recovery']['policy'], 'at_least_once')
            self.assertEqual(report['recovery']['counter_scope'], 'since_retry_policy_enabled')
            self.assertEqual(set(report['rubrics']), {'domain', 'satisfaction', 'corrections', 'quality_correction', 'quality_outcome'})
            self.assertTrue(report['privacy']['automatic_retry'])
            self.assertIn('dashboard_html', json.loads(out.getvalue())['artifacts'])
            self.assertFalse(state.exists(), 'only remove minimal labels after durable exports')
            third = self.helper.client()
            self.assertEqual(self.helper.invoke(source, work, third,
                ['--resume', '--retry-transient', '--retry-backoff', '0'])[0], 0)
            self.assertEqual(third.calls, 0)

    def test_retry_mode_handles_multiple_504s_without_inflating_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.helper.source(root); work = root / 'exports'
            client = self.helper.client(); original = client.classify; attempts = []
            def transient(*args):
                attempts.append(1)
                if len(attempts) in (2, 3, 9):
                    raise ClientError('http_504')
                return original(*args)
            client.classify = transient
            rc, _, err = self.helper.invoke(source, work, client,
                ['--retry-transient', '--retry-backoff', '0'])
            self.assertEqual(rc, 0, err.getvalue())
            report = json.loads((work / 'report.json').read_text())
            self.assertEqual(report['recovery']['errors']['http_504'], 3)
            self.assertEqual(report['recovery']['attempts'], report['planned_classifier_calls'] + 3)
            self.assertEqual(report['confirmed_classifier_calls'], report['planned_classifier_calls'])
            self.assertIn('"event": "retry"', err.getvalue())
            for file in work.iterdir():
                self.assertNotIn('PRIVATE-TEXT-SENTINEL', file.read_text())

    def test_recovery_flags_require_same_campaign_and_checkpoint_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.helper.source(root); work = root / 'exports'
            for flags in (['--recover-uncertain'], ['--retry-transient', '--ram-only'],
                          ['--retry-transient', '--retry-attempts', '0']):
                client = self.helper.client()
                rc, _, _ = self.helper.invoke(source, work, client, flags)
                self.assertEqual(rc, 2)
                self.assertEqual(client.calls, 0)
                self.assertFalse(work.exists())


if __name__ == '__main__':
    unittest.main()
