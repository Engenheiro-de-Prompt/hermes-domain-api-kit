import tempfile
import unittest
import zipfile
from pathlib import Path

from bundle import package_results


class BundleTests(unittest.TestCase):
    def test_bundle_contains_only_allowlisted_outputs_and_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            result=root/'classification'
            (result/'datasets').mkdir(parents=True)
            (result/'summary.json').write_text('{"total_items":1}',encoding='utf-8')
            (result/'dataset.csv').write_text('id;categoria\n1;pessoal\n',encoding='utf-8')
            from study import LABELS
            for label in LABELS:
                (result/'datasets'/f'{label}.jsonl').write_text('{"id":"1"}\n' if label=='pessoal' else '',encoding='utf-8')
            (result/'decisions.sqlite').write_text('private checkpoint',encoding='utf-8')
            secret=root/'client.key';secret.write_text('synthetic-secret',encoding='utf-8')
            archive=package_results(result,root/'classification_bundle.zip')
            self.assertEqual(archive,root/'classification_bundle.zip')
            with zipfile.ZipFile(archive) as bundle:
                names=set(bundle.namelist())
                self.assertEqual(names,{'summary.json','dataset.csv'}|{f'datasets/{label}.jsonl' for label in LABELS})
                self.assertNotIn('synthetic-secret',bundle.read('dataset.csv').decode())
            if __import__('os').name=='posix':
                self.assertEqual(archive.stat().st_mode & 0o777,0o600)


if __name__=='__main__':unittest.main()
