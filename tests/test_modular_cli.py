import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli


class ModularCliTests(unittest.TestCase):
    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as error:
                code = error.code
        return code, out.getvalue(), err.getvalue()

    def test_discover_rubrics_offline_without_key_or_http(self):
        with patch('cli.configured_client', side_effect=AssertionError('no_network')):
            code, out, _ = self.invoke(['rubrics'])
        self.assertEqual(code, 0)
        self.assertEqual({r['id'] for r in json.loads(out)['rubrics']}, {'domain', 'feedback', 'satisfaction', 'corrections'})

    def test_analyze_requires_authorization_before_io(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('cli.configured_client', side_effect=AssertionError('no_network')):
                code, _, err = self.invoke(['analyze', '--work', directory])
            self.assertEqual(code, 2)
            self.assertIn('relay_consent_required', err)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_extract_selected_only_reads_requested_skills_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / 'home'; (home / 'skills').mkdir(parents=True)
            (home / 'skills' / 'SKILL.md').write_text('Procedimento sintético genérico.', encoding='utf-8')
            work = root / 'work'
            with patch('cli.configured_client', side_effect=AssertionError('no_network')):
                code, out, err = self.invoke(['extract-selected', '--home', str(home), '--work', str(work), '--sources', 'skills'])
            self.assertEqual(code, 0, err)
            corpus = json.loads((work / 'corpus.json').read_text(encoding='utf-8'))
            self.assertEqual([x['kind'] for x in corpus['items']], ['skill'])
            self.assertEqual(corpus['coverage']['status'], 'ok')
            self.assertEqual(corpus['selection']['sources'], ['skills'])

    def test_domain_default_does_not_duplicate_requests_as_feedback(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); home = root/'home'; home.mkdir()
            db = sqlite3.connect(home/'state.db')
            try:
                db.executescript('CREATE TABLE sessions(id TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT);')
                db.execute("INSERT INTO sessions VALUES ('s')")
                db.execute("INSERT INTO messages VALUES (1,'s','user','Planeje férias em família.')")
                db.commit()
            finally:
                db.close()
            work = root/'work'
            code, _, err = self.invoke(['extract-selected','--home',str(home),'--work',str(work)])
            self.assertEqual(code, 0, err)
            corpus = json.loads((work/'corpus.json').read_text(encoding='utf-8'))
            self.assertEqual([x['kind'] for x in corpus['items']], ['task'])
            self.assertEqual(corpus['selection']['sources'], ['tasks','skills','memories'])

    def test_snapshot_tampering_blocks_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); home = root/'home'; (home/'skills').mkdir(parents=True)
            (home/'skills'/'SKILL.md').write_text('Procedimento genérico.',encoding='utf-8')
            work = root/'work'
            self.assertEqual(self.invoke(['extract-selected','--home',str(home),'--work',str(work),'--sources','skills'])[0], 0)
            path = work/'corpus.json'; corpus = json.loads(path.read_text(encoding='utf-8'))
            corpus['coverage']['status'] = 'changed'
            path.write_text(json.dumps(corpus),encoding='utf-8')
            with patch('cli.configured_client', side_effect=AssertionError('no_network')):
                code, _, err = self.invoke(['analyze','--work',str(work),'--allow-relay'])
            self.assertEqual(code, 2)
            self.assertIn('snapshot_integrity_failed', err)

    def test_verify_analysis_is_synthetic_only_and_reports_semantic_failure(self):
        from analysis import load_rubric
        labels = load_rubric('feedback')['criteria']
        class Client:
            base_url = 'https://example.invalid/v1'
            def models(self):
                return {'data':[{'id':'clef-fixture','task':'classification'}]}
            def classify(self, model, state, questions):
                return {'model':model, 'answers':{'classificacao':{'choice':'neutro','probabilities':{x:float(x=='neutro') for x in labels}}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch('cli.configured_client', return_value=Client()):
                code, out, err = self.invoke(['verify-analysis','--rubric','feedback','--work',str(root/'work'),'--allow-relay'])
            self.assertEqual(code, 1, err)
            result = json.loads(out)
            self.assertEqual(result['total'], 5)
            self.assertEqual(result['matched'], 1)
            self.assertFalse(result['all_expected_labels_matched'])
            self.assertEqual(result['qualification'], 'not_established_smoke_only')
            self.assertFalse((root/'work'/'corpus.json').exists())

    def test_feedback_extract_http_analysis_resume_and_scope_integrity(self):
        import os
        import sqlite3
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        calls = []
        labels = ['correcao_redirecionamento', 'insatisfacao', 'confirmacao_positiva', 'neutro', 'indeterminado']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'data':[{'id':'clef-fixture','task':'classification'}]}).encode())
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(body)
                result = {'model':'clef-fixture','answers':{'classificacao':{'type':'choice', 'confidence':1.0, 'choice':labels[0], 'probabilities':{x:float(x==labels[0]) for x in labels}}}}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
        server = HTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); home = root/'home'; home.mkdir(); work = root/'work'
                db = sqlite3.connect(home/'state.db')
                db.executescript('CREATE TABLE sessions(id TEXT,source TEXT,title TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL);')
                db.execute('INSERT INTO sessions VALUES (?,?,?)',('sample','cli','Sintético'))
                db.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', [(1,'sample','assistant','Entreguei uma lista sem ordenar.',1), (2,'sample','user','Não, organize por prioridade.',2)])
                db.commit(); db.close()
                code, _, err = self.invoke(['extract-selected','--rubric','feedback','--home',str(home),'--work',str(work),'--session','sample'])
                self.assertEqual(code, 0, err)
                key = root/'client.key'; key.write_text('synthetic-client',encoding='utf-8'); os.chmod(key,0o600)
                argv = ['analyze','--rubric','feedback','--work',str(work),'--allow-relay','--base-url',f'http://127.0.0.1:{server.server_port}/v1','--key-file',str(key)]
                for _ in range(2):
                    code, out, err = self.invoke(argv)
                    self.assertEqual(code, 0, err)
                    self.assertEqual(json.loads(out)['completed'], 1)
                self.assertEqual(len(calls), 1)
                state = json.loads(calls[0]['state'])
                self.assertEqual(state['texto'], 'Não, organize por prioridade.')
                self.assertIn('sem ordenar', state['contexto'])
                self.assertEqual(set(calls[0]['questions']['classificacao']['criteria']), set(labels))
                code, _, err = self.invoke(argv + ['--sources','tasks'])
                self.assertEqual(code, 2)
                self.assertEqual(len(calls), 1)
                self.assertIn('selection_options_only_at_extraction', err)
                checkpoint = work/'analysis'/'decisions.sqlite'
                checkpoint.unlink()
                code, _, err = self.invoke(argv)
                self.assertEqual(code, 2)
                self.assertIn('checkpoint_incomplete', err)
                self.assertEqual(len(calls), 1)
                self.assertFalse(checkpoint.exists())
        finally:
            server.shutdown(); server.server_close(); thread.join()
