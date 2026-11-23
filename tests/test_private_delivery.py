"""Private CLI reports must expose their automatically generated HTML artifacts."""
import json
from pathlib import Path
import tempfile
import unittest
import test_private_resume


class DashboardDeliveryTests(unittest.TestCase):
    source = test_private_resume.PrivateResumeTests.source
    invoke = test_private_resume.PrivateResumeTests.invoke
    client = test_private_resume.PrivateResumeTests.client

    def test_completed_resume_reexposes_dashboards_without_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / 'exports'
            source = self.source(root)
            self.assertEqual(self.invoke(source, work, self.client())[0], 0)
            before = {path.name: path.read_bytes() for path in work.iterdir()}
            client = self.client()
            rc, out, err = self.invoke(source, work, client, ['--resume'])
            self.assertEqual(rc, 0, err.getvalue())
            self.assertEqual(client.calls, 0)
            result = json.loads(out.getvalue())
            self.assertTrue(result['already_completed'])
            self.assertEqual(result.get('artifacts'), {
                'dashboard_html': str(work / 'dashboard.html'),
                'feedback_html': str(work / 'feedback.html'),
            })
            self.assertEqual(before, {path.name: path.read_bytes() for path in work.iterdir()})

    def test_partial_analysis_exposes_dashboards_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / 'exports'
            rc, out, err = self.invoke(self.source(root), work, self.client(fail_at=3))
            self.assertEqual(rc, 1, err.getvalue())
            result = json.loads(out.getvalue())
            self.assertFalse(result['complete'])
            self.assertEqual(set(result['artifacts']), {'dashboard_html', 'feedback_html'})
            for path in result['artifacts'].values():
                self.assertIn('PARCIAL', Path(path).read_text(encoding='utf-8'))

    def test_missing_completed_dashboard_blocks_handoff_without_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = self.source(root)
            work = root / 'exports'
            self.assertEqual(self.invoke(source, work, self.client())[0], 0)
            (work / 'dashboard.html').unlink()
            client = self.client()
            rc, out, _ = self.invoke(source, work, client, ['--resume'])
            self.assertEqual(rc, 2)
            self.assertEqual(client.calls, 0)
            self.assertNotIn('artifacts', out.getvalue())
            self.assertFalse((work / 'dashboard.html').exists())

    def test_completed_analysis_identifies_both_generated_dashboards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / 'exports'
            rc, out, err = self.invoke(self.source(root), work, self.client())
            self.assertEqual(rc, 0, err.getvalue())
            result = json.loads(out.getvalue())
            self.assertTrue(result['complete'])
            self.assertEqual(result.get('artifacts'), {
                'dashboard_html': str(work / 'dashboard.html'),
                'feedback_html': str(work / 'feedback.html'),
            })
            for path in result['artifacts'].values():
                self.assertIn('<body', Path(path).read_text(encoding='utf-8'))
