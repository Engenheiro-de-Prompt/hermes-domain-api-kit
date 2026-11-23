"""Offline durability barriers and idempotent completion, synthetic files only."""
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import private_checkpoint
import unittest
import test_private_resume


class DurabilityTests(unittest.TestCase):
    source = test_private_resume.PrivateResumeTests.source
    invoke = test_private_resume.PrivateResumeTests.invoke
    client = test_private_resume.PrivateResumeTests.client
    def test_resume_existing_output_syncs_parent_before_finish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            def interrupted(output, files):
                output.mkdir(mode=0o700)
                raise OSError('synthetic interrupted mkdir')
            with patch('private_pipeline._save', side_effect=interrupted):
                self.assertEqual(self.invoke(source, work, self.client())[0], 2)
            observed = []
            sync = private_checkpoint.sync_directory
            finish = private_checkpoint.Journal.finish
            def tracked_sync(path):
                observed.append(Path(path))
                sync(path)
            def tracked_finish(journal, exports):
                self.assertIn(work, observed)
                self.assertIn(work.parent, observed)
                self.assertLess(observed.index(work), observed.index(work.parent))
                finish(journal, exports)
            with patch('private_checkpoint.sync_directory', side_effect=tracked_sync), patch('private_checkpoint.Journal.finish', tracked_finish):
                self.assertEqual(self.invoke(source, work, None, ['--resume'])[0], 0)

    def test_completed_resume_cleans_state_only_after_export_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            self.assertEqual(self.invoke(source, work, self.client())[0], 0)
            state = root / 'exports.checkpoint' / 'state.json'
            state.write_text('{"synthetic":"leftover"}')
            report = work / 'report.json'; original = report.read_bytes()
            report.write_text('{}')
            self.assertEqual(self.invoke(source, work, None, ['--resume'])[0], 2)
            self.assertTrue(state.exists())
            report.write_bytes(original)
            self.assertEqual(self.invoke(source, work, None, ['--resume'])[0], 0)
            self.assertFalse(state.exists())
            self.assertEqual(self.invoke(source, work, None, ['--resume'])[0], 0)

    def test_atomic_text_explicit_lf(self):
        with tempfile.TemporaryDirectory() as temp:
            original = os.fdopen
            def checked(*args, **kwargs):
                self.assertEqual(kwargs.get('newline'), '\n')
                return original(*args, **kwargs)
            with patch('private_checkpoint.os.fdopen', side_effect=checked):
                private_checkpoint.atomic_text(Path(temp).resolve() / 'synthetic.txt', 'a\nb\n')
            self.assertEqual((Path(temp).resolve() / 'synthetic.txt').read_bytes(), b'a\nb\n')
