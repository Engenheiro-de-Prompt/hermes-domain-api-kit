"""Regressões do fluxo simplificado; dados exclusivamente sintéticos."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cli


class OnboardingTests(unittest.TestCase):
    def test_agent_key_error_explains_client_role_without_echo(self):
        import os
        key='lr_'+'agent_synthetic_onboarding'
        err=io.StringIO()
        with patch.dict(os.environ,{'HERMES_CLASSIFIER_API_KEY':key,'HERMES_CLASSIFIER_KEY_FILE':''}), contextlib.redirect_stderr(err):
            code=cli.main(['models','--base-url','https://api.example.com/api/public/v1'])
        self.assertEqual(code,2)
        result=json.loads(err.getvalue())
        self.assertEqual(result['error'],'invalid_key')
        self.assertIn('hint',result)
        self.assertIn('CLIENT',result['hint'])
        self.assertIn('AGENT',result['hint'])
        self.assertNotIn(key,err.getvalue())

    def test_invalid_agent_key_is_rejected_before_extracting_real_scope(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'campaign'
            err=io.StringIO()
            with patch.dict(os.environ,{'HERMES_CLASSIFIER_API_KEY':'lr_'+'agent_synthetic_preflight','HERMES_CLASSIFIER_KEY_FILE':''}), patch('extractor.extract',side_effect=AssertionError('source_access_forbidden')), contextlib.redirect_stderr(err):
                code=cli.main(['classify-all','--allow-relay','--work',str(work)])
            self.assertEqual(code,2)
            self.assertEqual(json.loads(err.getvalue())['error'],'invalid_key')
            self.assertFalse(work.exists())

    def test_resume_rejects_another_home_before_http(self):
        import os
        from study import digest,save_json
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'campaign'
            corpus={'items':[],'items_sha256':digest([]),'source_home_sha256':digest(str((Path(tmp)/'first-home').resolve())),'coverage':{'status':'ok'}}
            save_json(work/'corpus.json',corpus)
            err=io.StringIO()
            with patch.dict(os.environ,{'HERMES_CLASSIFIER_API_KEY':'synthetic-client','HERMES_CLASSIFIER_KEY_FILE':''}), patch('cli.select_model',side_effect=AssertionError('network_forbidden')), contextlib.redirect_stderr(err):
                code=cli.main(['classify-all','--allow-relay','--home',str(Path(tmp)/'second-home'),'--work',str(work)])
            self.assertEqual(code,2)
            self.assertEqual(json.loads(err.getvalue().splitlines()[-1])['error'],'source_home_mismatch')

    def test_campaign_path_is_reported_even_when_no_items(self):
        import os
        from study import digest,save_json
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'campaign'
            home=Path(tmp)/'home'
            save_json(work/'corpus.json',{'items':[],'items_sha256':digest([]),'source_home_sha256':digest(str(home.resolve())),'coverage':{'status':'ok'}})
            err=io.StringIO()
            with patch.dict(os.environ,{'HERMES_CLASSIFIER_API_KEY':'synthetic-client','HERMES_CLASSIFIER_KEY_FILE':''}), contextlib.redirect_stderr(err):
                code=cli.main(['classify-all','--allow-relay','--home',str(home),'--work',str(work)])
            self.assertEqual(code,2)
            first=json.loads(err.getvalue().splitlines()[0])
            self.assertEqual(first.get('event'),'campaign')
            self.assertEqual(first['work'],str(work.resolve()))
            self.assertNotIn('synthetic-client',err.getvalue())

    def test_classify_all_requires_consent_before_source_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'campaign'
            out=io.StringIO()
            with patch('extractor.extract',side_effect=AssertionError('source_access_forbidden')), contextlib.redirect_stderr(out):
                code=cli.main(['classify-all','--work',str(work)])
            self.assertEqual(code,2)
            self.assertEqual(json.loads(out.getvalue())['error'],'relay_consent_required')
            self.assertFalse(work.exists())


if __name__=='__main__':unittest.main()
