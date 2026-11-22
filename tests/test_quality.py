"""Aceites offline: eventos e fontes exclusivamente sintéticos."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def event(eid, kind, timestamp, **fields):
    return dict(event_id=eid, tenant_id='synthetic', source_id='fixture',
                session_id='s1', task_id='objective1', event_type=kind,
                timestamp=timestamp, **({'source_complete': True} | fields))


class QualityTests(unittest.TestCase):
    def test_reject_tenant_mix_before_evaluation(self):
        import quality
        events = [event('1', 'request', 0), dict(event('2', 'request', 1), tenant_id='other')]
        with self.assertRaisesRegex(ValueError, '^tenant_mismatch$'):
            quality.evaluate(events, tenant_id='synthetic')

    def test_unverified_claim_and_silence_remain_unknown(self):
        import quality
        for ending in ('delivery', 'session_end', 'resolved'):
            events = [event('1', 'request', 0), event('2', 'attempt', 10, attempt_id='a1'),
                      event('3', ending, 20, actor='assistant')]
            task, report = quality.evaluate(events, tenant_id='synthetic')
            self.assertEqual(task[0]['outcome'], 'unknown')
            self.assertIsNone(task[0]['first_attempt_resolved'])
            self.assertEqual(task[0].get('satisfaction'), 'unknown')
            self.assertEqual(report['metrics']['first_attempt_resolution']['denominator'], 0)
            self.assertEqual(report['metrics']['unknown_resolution']['numerator'], 1)

    def test_event_identity_dedup_order_and_conflicts(self):
        import quality
        a = event('1', 'request', 0)
        b = event('2', 'attempt', 10, attempt_id='a1')
        c = event('3', 'resolved', 60, attempt_id='a1', actor='user')
        tasks, report = quality.evaluate([c, a, b, b], tenant_id='synthetic')
        self.assertEqual(tasks[0]['source_event_ids'], ['1', '2', '3'])
        self.assertEqual(report['coverage']['duplicate_events'], 1)
        with self.assertRaisesRegex(ValueError, '^event_identity_conflict$'):
            quality.evaluate([a, dict(a, timestamp=5)], tenant_id='synthetic')
        with self.assertRaisesRegex(ValueError, '^invalid_event$'):
            quality.evaluate([dict(a, event_type='made_up')], tenant_id='synthetic')
        with self.assertRaisesRegex(ValueError, '^invalid_event$'):
            quality.evaluate([dict(a, timestamp=float('nan'))], tenant_id='synthetic')

    def test_missing_links_or_timestamps_cannot_prove_first_attempt(self):
        import quality
        cases = [
            [event('1', 'request', None), event('2', 'resolved', 60, actor='user', attempt_id='missing')],
            [event('1', 'request', 0, association_uncertain=True), event('2', 'attempt', 1, attempt_id='a'), event('3', 'resolved', 60, actor='user', attempt_id='a')],
            [event('1', 'request', 0), event('2', 'resolved', 60, actor='user', attempt_id='missing')],
        ]
        for events in cases:
            tasks, report = quality.evaluate(events, tenant_id='synthetic')
            self.assertIsNone(tasks[0]['first_attempt_resolved'])
        events = [dict(event('1', 'request', 0), task_id=None),
                  dict(event('2', 'resolved', 60, actor='user'), task_id=None, session_id='other')]
        tasks, report = quality.evaluate(events, tenant_id='synthetic')
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t['association_uncertain'] for t in tasks))
        self.assertTrue(all(t['outcome'] == 'unknown' for t in tasks))

    def test_planned_approval_clarification_and_tool_failure_are_not_corrections(self):
        import quality
        events = [event('1', 'request', 0),
                  event('2', 'intervention', 2, intervention_type='aprovacao', actor='user'),
                  event('3', 'intervention', 3, intervention_type='esclarecimento', actor='user'),
                  event('4', 'tool_failure', 4, failure_class='timeout'),
                  event('5', 'attempt', 5, attempt_id='a1'),
                  event('6', 'resolved', 6, actor='user', attempt_id='a1')]
        tasks, report = quality.evaluate(events, tenant_id='synthetic')
        self.assertEqual(tasks[0]['correction_count'], 0)
        self.assertEqual(tasks[0].get('interventions'), {'aprovacao': 1, 'esclarecimento': 1})
        self.assertEqual(tasks[0].get('action_failure_count'), 1)
        self.assertTrue(tasks[0]['first_attempt_resolved'])

    def test_legacy_selected_snapshot_never_invents_task_links(self):
        import quality
        import selection
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            with sqlite3.connect(home / 'state.db') as db:
                db.execute('CREATE TABLE sessions(id TEXT)')
                db.execute("INSERT INTO sessions VALUES ('s')")
                db.execute('CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT, timestamp REAL)')
                db.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', [
                    (1, 's', 'user', 'Faça um relatório sintético', 0),
                    (2, 's', 'assistant', 'Pronto', 10),
                    (3, 's', 'user', 'Confirmo o recebimento', 20)])
            selected = selection.extract_selected(home, sources=('feedback',))
            events = quality.from_selected(selected, tenant_id='synthetic', source_id='fixture')
            tasks, report = quality.evaluate(events, tenant_id='synthetic')
            self.assertEqual(len(tasks), 1)
            self.assertTrue(tasks[0]['association_uncertain'])
            self.assertEqual(tasks[0]['outcome'], 'unknown')
            self.assertEqual(len(tasks[0]['source_event_ids']), 2)
            self.assertEqual(report['coverage']['missing_task_id'], 2)

    def test_abandonment_is_not_timeout_and_recent_is_censored(self):
        import quality
        base = [event('1', 'request', 0), event('2', 'attempt', 1, attempt_id='a')]
        tasks, _ = quality.evaluate(base + [event('3', 'abandoned', 2, actor='user')], tenant_id='synthetic', as_of=100, inactivity_seconds={'default': 10})
        self.assertEqual(tasks[0]['abandonment'], 'explicit')
        tasks, _ = quality.evaluate(base, tenant_id='synthetic', as_of=5, inactivity_seconds={'default': 10})
        self.assertEqual(tasks[0]['abandonment'], 'right_censored')
        tasks, _ = quality.evaluate(base, tenant_id='synthetic', as_of=100, inactivity_seconds={'default': 10})
        self.assertEqual(tasks[0]['abandonment'], 'possible')
        self.assertEqual(tasks[0]['outcome'], 'unknown')
        tasks, _ = quality.evaluate(base + [event('3', 'session_end', 2)], tenant_id='synthetic', as_of=100, inactivity_seconds={'default': 10})
        self.assertEqual(tasks[0]['abandonment'], 'natural_session_end')

    def test_cost_tokens_missing_are_null_not_zero(self):
        import quality
        base = [event('1', 'request', 0), event('2', 'attempt', 1, attempt_id='a1'),
                event('3', 'resolved', 2, attempt_id='a1', actor='user')]
        tasks, _ = quality.evaluate(base, tenant_id='synthetic')
        self.assertIsNone(tasks[0].get('cost', 'missing'))
        self.assertIsNone(tasks[0].get('tokens', 'missing'))
        priced = [base[0], dict(base[1], cost=1.5, currency='USD', tokens=25), base[2]]
        tasks, _ = quality.evaluate(priced, tenant_id='synthetic')
        self.assertEqual(tasks[0]['cost'], 1.5)
        self.assertEqual(tasks[0]['tokens'], 25)
        tasks, _ = quality.evaluate(priced + [event('4', 'attempt', 3, attempt_id='a2')], tenant_id='synthetic')
        self.assertIsNone(tasks[0]['cost'])
        for change in ({'cost': -1, 'currency': 'USD'}, {'cost': float('inf'), 'currency': 'USD'}, {'tokens': True}):
            with self.assertRaisesRegex(ValueError, '^invalid_event$'):
                quality.evaluate([base[0], dict(base[1], **change), base[2]], tenant_id='synthetic')

    def test_known_failure_stays_in_first_attempt_denominator(self):
        import quality
        events = [event('1', 'request', 0), event('2', 'attempt', 1, attempt_id='a1'),
                  event('3', 'unresolved', 5, actor='user', attempt_id='a1')]
        tasks, report = quality.evaluate(events, tenant_id='synthetic')
        self.assertEqual(tasks[0]['outcome'], 'unresolved')
        self.assertFalse(tasks[0]['first_attempt_resolved'])
        self.assertEqual(report['metrics']['first_attempt_resolution']['denominator'], 1)
        self.assertEqual(report['metrics']['first_attempt_resolution']['numerator'], 0)

    def test_cli_frozen_campaign_rejects_changed_input_and_preserves_outputs(self):
        events = [event('1', 'request', 0)]
        with tempfile.TemporaryDirectory() as td:
            source, work = Path(td) / 'events.json', Path(td) / 'work'
            source.write_text(json.dumps({'schema_version': 1, 'events': events}))
            cmd = [sys.executable, '-B', str(ROOT / 'cli.py'), 'quality-report',
                   '--input', str(source), '--tenant', 'synthetic', '--work', str(work)]
            first = subprocess.run(cmd, capture_output=True)
            self.assertEqual(first.returncode, 0)
            path = work / 'quality' / 'report.json'
            previous = path.read_bytes()
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(path.read_bytes(), previous)
            source.write_text(json.dumps({'schema_version': 1, 'events': events + [event('2', 'request', 2,)]}))
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(path.read_bytes(), previous)

    def test_closed_enums_and_flags_are_validated_without_echo(self):
        import quality
        for fields in ({'actor': 'synthetic-private-marker'}, {'severity': 'not_valid'},
                       {'correction_type': 'made_up'}, {'intervention_type': 'made_up'},
                       {'association_uncertain': 'false'}, {'source_complete': 1},
                       {'task_id': []}, {'extra': 'not_allowed'}):
            with self.assertRaisesRegex(ValueError, '^invalid_event$'):
                quality.evaluate([dict(event('1', 'request', 0), **fields)], tenant_id='synthetic')

    def test_extra_attempt_or_repair_prevents_false_first_success(self):
        import quality
        base = [event('1', 'request', 0), event('2', 'attempt', 1, attempt_id='a1'),
                event('3', 'attempt', 2, attempt_id='a2'), event('4', 'resolved', 4, actor='user', attempt_id='a1')]
        tasks, _ = quality.evaluate(base, tenant_id='synthetic')
        self.assertFalse(tasks[0]['first_attempt_resolved'])
        tasks, _ = quality.evaluate(base + [event('5', 'correction', 5, actor='user')], tenant_id='synthetic')
        self.assertEqual(tasks[0]['outcome'], 'unknown')
        self.assertIsNone(tasks[0]['first_attempt_resolved'])

    def test_explicit_objective_link_crosses_sessions_but_new_objective_does_not(self):
        import quality
        events = [event('1', 'request', 0, workflow='fixture_workflow', agent_id='a', agent_version='v1'),
                  event('2', 'attempt', 1, attempt_id='a1'),
                  dict(event('3', 'resolved', 5, actor='user', attempt_id='a1'), session_id='second'),
                  dict(event('4', 'request', 10), task_id='new_objective')]
        tasks, _ = quality.evaluate(events, tenant_id='synthetic')
        self.assertEqual(len(tasks), 2)
        resolved = next(t for t in tasks if t['outcome'] == 'resolved_with_evidence')
        self.assertEqual(resolved.get('session_ids'), ['s1', 'second'])
        self.assertEqual(resolved.get('workflow'), 'fixture_workflow')
        self.assertEqual(resolved.get('start_timestamp'), 0)
        self.assertEqual(resolved.get('agent_version'), 'v1')
        self.assertEqual(sum(t['outcome'] == 'unknown' for t in tasks), 1)

    def test_cli_inference_cannot_overrule_missing_observed_resolution(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'data': [{'id': 'clef-flash-9b-q4-k-m', 'task': 'classification'}]}).encode())
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(data)
                criteria = data['questions']['classificacao']['criteria']
                label = 'resolvida_com_evidencia' if 'resolvida_com_evidencia' in criteria else 'sim'
                response = {'model': data['model'], 'answers': {'classificacao': {'type': 'choice',
                            'confidence': 1.0, 'choice': label,
                            'probabilities': {k: float(k == label) for k in criteria}}}}
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(response).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                source, key, work = Path(td) / 'events.json', Path(td) / 'client.key', Path(td) / 'work'
                key.write_text('synthetic-key'); key.chmod(0o600)
                events = [event('1', 'request', 0), event('2', 'attempt', 1, attempt_id='a1'),
                          event('3', 'delivery', 2, actor='assistant', text='Entrega feita, conforme alegado pelo assistente.')]
                source.write_text(json.dumps({'schema_version': 1, 'events': events}))
                cmd = [sys.executable, '-B', str(ROOT / 'cli.py'), 'quality-analyze', '--input', str(source),
                       '--tenant', 'synthetic', '--work', str(work), '--base-url',
                       'http://127.0.0.1:' + str(server.server_port), '--key-file', str(key), '--allow-relay']
                import os
                env = dict(os.environ); env.pop('HERMES_CLASSIFIER_API_KEY', None)
                result = subprocess.run(cmd, capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                tasks = [json.loads(line) for line in (work/'quality'/'tasks.jsonl').read_text().splitlines()]
                self.assertEqual(tasks[0]['outcome'], 'unknown')
                self.assertTrue(tasks[0]['classifications'])
                self.assertTrue(all(l['review_required'] for l in tasks[0]['classifications']))
                self.assertTrue(calls)
                count = len(calls)
                result = subprocess.run(cmd, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(len(calls), count)
                import shutil
                classification = work / 'quality' / 'classification'
                shutil.rmtree(classification)
                before = {p.name: p.read_bytes() for p in (work / 'quality').iterdir() if p.is_file()}
                blocked = subprocess.run(cmd, capture_output=True, text=True, env=env)
                self.assertEqual(blocked.returncode, 2)
                self.assertIn('checkpoint_incomplete', blocked.stderr)
                self.assertEqual(len(calls), count)
                self.assertFalse(classification.exists())
                self.assertEqual(before, {p.name: p.read_bytes() for p in (work / 'quality').iterdir() if p.is_file()})
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_classifier_budget_blocks_before_any_client_or_secret_read(self):
        with tempfile.TemporaryDirectory() as td:
            source, work = Path(td) / 'events.json', Path(td) / 'work'
            source.write_text(json.dumps({'schema_version': 1, 'events': [event('1', 'delivery', 0, actor='assistant', text='x' * 5000)]}))
            proc = subprocess.run([sys.executable, '-B', str(ROOT / 'cli.py'), 'quality-analyze',
                                   '--input', str(source), '--tenant', 'synthetic', '--work', str(work),
                                   '--allow-relay', '--max-classifier-calls', '1'], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('classifier_budget_exceeded', proc.stderr)
            self.assertFalse((work / 'quality' / 'classification').exists())

    def test_field_coverage_reports_absence_and_partial_sources(self):
        import quality
        tasks, report = quality.evaluate([event('1', 'request', None, source_complete=False)], tenant_id='synthetic')
        fields = report['coverage'].get('fields', {})
        self.assertEqual(fields.get('timestamp'), {'present': 0, 'total': 1})
        self.assertEqual(fields.get('cost'), {'present': 0, 'total': 1})
        self.assertEqual(report['coverage'].get('partial_source_events'), 1)
        self.assertIsNone(tasks[0]['extra_attempts'])

    def test_duration_p75_is_explicit_nearest_rank(self):
        from quality_metrics import aggregate
        report = aggregate([{'outcome': 'resolved_with_evidence', 'resolution_seconds': t} for t in (60, 180)])
        self.assertEqual(report['resolution_seconds'].get('p75'), 180)

    def test_resumed_task_invalidates_prior_abandonment_or_session_end(self):
        import quality
        for ending in ('abandoned', 'session_end'):
            for session in ('s1', 's2'):
                events = [event('1', 'request', 0),
                          event('2', 'attempt', 1, attempt_id='a1'),
                          event('3', ending, 2, actor='user'),
                          dict(event('4', 'attempt', 99, attempt_id='a2'), session_id=session)]
                tasks, report = quality.evaluate(events, tenant_id='synthetic', as_of=100,
                                                 inactivity_seconds={'default': 10})
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]['abandonment'], 'right_censored')
                self.assertEqual(report['metrics']['abandonment']['explicit']['numerator'], 0)
                self.assertEqual(tasks[0]['source_event_ids'], ['1', '2', '3', '4'])

    def test_unspecified_completeness_is_not_assumed(self):
        import quality
        events = [event('1', 'request', 0), event('2', 'attempt', 1, attempt_id='a1'),
                  event('3', 'resolved', 2, attempt_id='a1', actor='user')]
        for e in events:
            e.pop('source_complete')
        tasks, report = quality.evaluate(events, tenant_id='synthetic')
        self.assertIsNone(tasks[0]['first_attempt_resolved'])
        self.assertEqual(report['metrics']['no_observed_correction']['denominator'], 0)

    def test_repair_second_attempt_not_first_response(self):
        import quality
        events = [event('1', 'request', 0),
                  event('2', 'attempt', 2, attempt_id='a1'),
                  event('3', 'correction', 3, actor='user', correction_type='factual', severity='alta'),
                  event('4', 'attempt', 4, attempt_id='a2'),
                  event('5', 'resolved', 8, attempt_id='a2', actor='external')]
        tasks, report = quality.evaluate(events, tenant_id='synthetic')
        self.assertFalse(tasks[0]['first_attempt_resolved'])
        self.assertEqual(tasks[0].get('correction_count'), 1)
        self.assertEqual(tasks[0].get('extra_attempts'), 1)
        self.assertEqual(report['metrics']['tasks_with_correction']['numerator'], 1)

    def test_cli_confirmed_first_attempt_end_to_end(self):
        events = [event('1', 'request', 0),
                  event('2', 'attempt', 10, attempt_id='a1'),
                  event('3', 'resolved', 60, attempt_id='a1', actor='user')]
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'events.json'
            source.write_text(json.dumps({'schema_version': 1, 'events': events}))
            work = Path(td) / 'work'
            proc = subprocess.run([sys.executable, '-B', str(ROOT / 'cli.py'),
                                   'quality-report', '--input', str(source), '--tenant',
                                   'synthetic', '--work', str(work)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads((work / 'quality' / 'report.json').read_text())
            self.assertEqual(data['metrics']['first_attempt_resolution']['numerator'], 1)
            self.assertEqual(data['metrics']['first_attempt_resolution']['denominator'], 1)
            self.assertEqual(data['metrics']['resolution_seconds']['median'], 60)
            task = json.loads((work / 'quality' / 'tasks.jsonl').read_text())
            self.assertEqual(task['outcome'], 'resolved_with_evidence')
            self.assertEqual(task['source_event_ids'], ['1', '2', '3'])
            dashboard = (work / 'quality' / 'dashboard.html').read_text()
            self.assertNotIn('objective1', dashboard)
            self.assertIn('O que podemos afirmar', dashboard)
            self.assertIn('O que ainda não podemos afirmar', dashboard)
            self.assertIn('1 / 1', dashboard)
            self.assertIn('Não mensurável', dashboard)
            self.assertIn('<details>', dashboard)


if __name__ == '__main__':
    unittest.main()
