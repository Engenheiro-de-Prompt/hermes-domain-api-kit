"""Regression: synthetic linked destinations must never corrupt external files."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import cli
import feedback_projection
import feedback_report


class FeedbackOutputSafetyTests(unittest.TestCase):
    def check_links(self, link):
        cases = [
            ('cli', 'report.json'), ('cli', 'unique/dashboard.html'),
            ('cli', 'pipeline.lock.sqlite'),
            ('report', 'report.json'), ('report', 'weekly.csv'),
            ('report', 'report.html'),
            ('projection', 'unique/corpus.json'),
            ('projection', 'unique/satisfaction/analysis/results.jsonl'),
            ('projection', 'unique/corrections/analysis/results.jsonl'),
            ('projection', 'unique/report.json'),
            ('projection', 'unique/weekly.csv'),
            ('projection', 'unique/report.html'),
        ]
        for entry, relative in cases:
            with self.subTest(entry=entry, destination=relative):
                with tempfile.TemporaryDirectory() as directory:
                    base = Path(directory).resolve()
                    work = base / 'work'
                    work.mkdir()
                    corpus = json.dumps({'items': [], 'coverage': {'status': 'ok'}})
                    (work / 'corpus.json').write_text(corpus, encoding='utf-8')
                    outside = base / 'outside.txt'
                    sentinel = b'SYNTHETIC_OUTSIDE_MUST_NOT_CHANGE'
                    outside.write_bytes(sentinel)
                    destination = work / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        link(outside, destination)
                    except OSError:
                        self.skipTest('Filesystem does not permit this link type')
                    blocked = False
                    try:
                        if entry == 'cli':
                            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                                blocked = cli.main(['feedback-report', '--work', str(work), '--timezone', 'UTC']) == 2
                        elif entry == 'report':
                            feedback_report.build(work, timezone_name='UTC')
                        else:
                            feedback_projection.project(work, timezone_name='UTC')
                    except ValueError:
                        blocked = True
                    self.assertEqual(outside.read_bytes(), sentinel)
                    self.assertTrue(blocked, 'Unsafe destinations must fail closed')
                    self.assertEqual((work / 'corpus.json').read_text(encoding='utf-8'), corpus)

    def test_hardlinked_destinations_are_rejected_before_writing(self):
        self.check_links(os.link)

    def test_symlinked_destinations_are_rejected_before_writing(self):
        self.check_links(os.symlink)


if __name__ == '__main__':
    unittest.main()
