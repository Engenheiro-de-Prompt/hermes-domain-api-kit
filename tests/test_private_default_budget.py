"""Large private campaigns do not inherit an artificial 100-call quota."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cli


class PrivateDefaultBudgetTests(unittest.TestCase):
    def test_default_dry_plan_accepts_more_than_100_calls_without_a_volume_quota(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source=root/'events.json';out=root/'output'
            events=[{'event_id':f'synthetic-event-{i}', 'tenant_id':'synthetic-tenant',
                     'source_id':'synthetic-source','session_id':'synthetic-session',
                     'task_id':f'synthetic-task-{i}','event_type':'request',
                     'timestamp':1704067200+i*60,'actor':'user','source_complete':False,
                     'text':'Por favor faça a tarefa profissional sintética.'} for i in range(70)]
            source.write_text(json.dumps({'schema_version':1,'events':events}))
            stdout,stderr=io.StringIO(),io.StringIO()
            with patch('cli.configured_client',side_effect=AssertionError('dry_run_must_not_use_network')), contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                rc=cli.main(['private-analyze','--input',str(source),'--tenant','synthetic-tenant',
                             '--work',str(out),'--dry-run','--timezone','UTC','--cutoff','2024-01-10'])
            self.assertEqual(rc,0,stderr.getvalue())
            plan=json.loads(stdout.getvalue())
            self.assertGreater(plan['estimated_classifier_calls'],100)
            self.assertTrue(plan['budget_sufficient'])
            self.assertFalse(plan['network_used'])
            self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
