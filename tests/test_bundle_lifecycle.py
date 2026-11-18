"""Offline lifecycle regressions using only synthetic, temporary campaigns."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
import zipfile

import bundle
import study


class SyntheticClient:
    base_url = 'https://synthetic.invalid'

    def __init__(self):
        self.calls = 0

    def classify(self, model, state, questions):
        self.calls += 1
        return {'model': model, 'answers': {'dominio': {
            'choice': 'pessoal',
            'probabilities': {label: int(label == 'pessoal') for label in study.LABELS},
        }}}


class BundleLifecycleTests(unittest.TestCase):
    def make_results(self, root):
        output = root / 'results'
        study.export([], output)
        return output

    def test_writable_fsync_and_exclusive_temp_preserve_other_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = self.make_results(root)
            archive = root / 'result.zip'
            sentinel = root / 'result.zip.tmp'
            sentinel.write_bytes(b'other execution')
            real_fsync = os.fsync
            real_replace = os.replace
            temporaries = []

            def writable_fsync(fd):
                # A zero-byte write rejects read-only descriptors on POSIX too.
                os.write(fd, b'')
                real_fsync(fd)

            def checked_replace(source, target):
                source = Path(source)
                self.assertEqual(source.parent, archive.parent)
                self.assertNotEqual(source, sentinel)
                self.assertEqual(sentinel.read_bytes(), b'other execution')
                with zipfile.ZipFile(source) as packed:
                    self.assertIsNone(packed.testzip())
                temporaries.append(source)
                return real_replace(source, target)

            with patch('bundle.os.fsync', side_effect=writable_fsync) as sync:
                with patch('bundle.os.replace', side_effect=checked_replace):
                    self.assertEqual(bundle.package_results(output, archive), archive)
                    bundle.package_results(output, archive)
            self.assertEqual(sync.call_count, 2)
            self.assertEqual(len(set(temporaries)), 2)
            self.assertTrue(all(not path.exists() for path in temporaries))
            self.assertEqual(sentinel.read_bytes(), b'other execution')

    def test_crc_failure_keeps_previous_archive_and_cleans_only_owned_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = self.make_results(root)
            archive = root / 'result.zip'
            archive.write_bytes(b'previous archive')
            sentinel = root / 'result.zip.tmp'
            sentinel.write_bytes(b'other execution')
            real_fsync = os.fsync

            def corrupt_crc(fd):
                real_fsync(fd)
                candidates = [p for p in root.iterdir()
                              if p.is_file() and p not in (archive, sentinel)]
                # The old implementation uses the fixed sentinel itself.
                temporary = candidates[0] if candidates else sentinel
                data = bytearray(temporary.read_bytes())
                central = data.index(b'PK\x01\x02')
                data[central + 16] ^= 1
                temporary.write_bytes(data)

            with patch('bundle.os.fsync', side_effect=corrupt_crc):
                with self.assertRaises(zipfile.BadZipFile):
                    bundle.package_results(output, archive)
            self.assertEqual(archive.read_bytes(), b'previous archive')
            self.assertEqual(sentinel.read_bytes(), b'other execution')
            self.assertEqual(set(root.iterdir()), {output, archive, sentinel})

    def attempt_lock(self, output):
        connection = sqlite3.connect(output / 'lock.sqlite', timeout=0)
        try:
            try:
                connection.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error:
                if 'locked' not in str(error):
                    raise
                return 'locked'
            return 'acquired'
        finally:
            connection.close()

    def test_packaging_holds_real_sqlite_lock_and_resume_keeps_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / 'campaign'
            archive = root / 'result.zip'
            client = SyntheticClient()
            items = [{'id': 'synthetic-1', 'kind': 'request', 'text': 'Lazer.'}]
            real_package = bundle.package_results
            observations = []

            def package_while_contended(result_dir, bundle_path):
                self.assertEqual(result_dir, output)
                self.assertEqual(bundle_path, archive)
                self.assertTrue((output / 'summary.json').is_file())
                with ThreadPoolExecutor(max_workers=1) as executor:
                    observations.append(executor.submit(self.attempt_lock, output).result(timeout=5))
                return real_package(result_dir, bundle_path)

            with patch('bundle.package_results', side_effect=package_while_contended):
                summary = study.classify_records(items, client, 'synthetic', output,
                                                 bundle_path=archive)
                resumed = study.classify_records(items, client, 'synthetic', output,
                                                 bundle_path=archive)
            self.assertEqual(observations, ['locked', 'locked'])
            self.assertEqual(self.attempt_lock(output), 'acquired')
            self.assertEqual(client.calls, 1)
            self.assertEqual(summary, resumed)
            self.assertEqual(summary['completed'], 1)
            with zipfile.ZipFile(archive) as packed:
                self.assertIsNone(packed.testzip())
                self.assertEqual(json.loads(packed.read('summary.json')), summary)

    def test_packaging_failure_releases_campaign_lock_without_losing_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / 'campaign'
            client = SyntheticClient()
            items = [{'id': 'synthetic-1', 'kind': 'request', 'text': 'Lazer.'}]
            with patch('bundle.package_results', side_effect=OSError('synthetic failure')):
                with self.assertRaisesRegex(OSError, 'synthetic failure'):
                    study.classify_records(items, client, 'synthetic', output,
                                           bundle_path=root / 'result.zip')
            self.assertEqual(self.attempt_lock(output), 'acquired')
            summary = study.classify_records(items, client, 'synthetic', output)
            self.assertEqual(summary['completed'], 1)
            self.assertEqual(client.calls, 1)


if __name__ == '__main__':
    unittest.main()
