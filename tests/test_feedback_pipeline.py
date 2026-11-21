"""Integração pública com SQLite e HTTP exclusivamente sintéticos."""
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
import cli


class FeedbackPipelineTests(unittest.TestCase):
    def invoke(self, argv):
        out, err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:code=cli.main(argv)
            except SystemExit as e:code=e.code
        return code,out.getvalue(),err.getvalue()

    def test_consent_precedes_profile_key_network_and_output(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)/'work'
            with patch('cli.configured_client',side_effect=AssertionError('network_forbidden')):
                code,_,err=self.invoke(['feedback-all','--work',str(work)])
            self.assertEqual(code,2)
            self.assertIn('relay_consent_required',err)
            self.assertFalse(work.exists())

    def test_incomplete_pipeline_blocks_before_client_configuration(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();home=root/'home';home.mkdir();work=root/'campaign';work.mkdir()
            (work/'corpus.json').write_text('{}',encoding='utf-8')
            with patch('cli.configured_client',side_effect=AssertionError('no_key_or_network')):
                code,out,err=self.invoke(['feedback-all','--allow-relay','--home',str(home),'--work',str(work)])
            self.assertEqual(code,2)
            self.assertIn('checkpoint_incomplete',err)
            self.assertFalse((work/'pipeline.json').exists())
            self.assertEqual((work/'corpus.json').read_text(encoding='utf-8'),'{}')

    def test_invalid_cutoff_does_not_create_output_or_read_profile(self):
        with tempfile.TemporaryDirectory() as d:
            work=Path(d).resolve()/'campaign'
            with patch('cli.configured_client',side_effect=AssertionError('no_key_or_network')):
                code,out,err=self.invoke(['feedback-all','--allow-relay','--cutoff','invalid','--work',str(work)])
            self.assertEqual(code,2)
            self.assertFalse(work.exists())

    def test_missing_timezone_data_blocks_before_output_and_api(self):
        from zoneinfo import ZoneInfoNotFoundError
        with tempfile.TemporaryDirectory() as d:
            work=Path(d).resolve()/'campaign'
            with patch('feedback_report.ZoneInfo',side_effect=ZoneInfoNotFoundError('synthetic')), patch('cli.configured_client',side_effect=AssertionError('no_key_or_network')):
                code,out,err=self.invoke(['feedback-all','--allow-relay','--work',str(work)])
            self.assertEqual(code,2)
            self.assertIn('timezone_data_missing',err)
            self.assertFalse(work.exists())

    def test_pipeline_lock_prevents_concurrent_reports(self):
        with tempfile.TemporaryDirectory() as d:
            work=Path(d).resolve()/'campaign';work.mkdir()
            lock=sqlite3.connect(work/'pipeline.lock.sqlite')
            try:
                lock.execute('BEGIN IMMEDIATE')
                code,out,err=self.invoke(['feedback-report','--work',str(work)])
                self.assertEqual(code,2)
                self.assertIn('pipeline_busy',err)
                self.assertFalse((work/'unique').exists())
            finally:lock.close()

    def test_one_command_extracts_two_dimensions_renders_and_resumes_without_http(self):
        calls=[];gets=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,format,*args):pass
            def do_GET(self):
                gets.append(self.path)
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps({'data':[{'id':'clef-fixture','task':'classification'}]}).encode())
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(body)
                labels=body['questions']['classificacao']['criteria']
                label='insatisfacao' if 'insatisfacao' in labels else 'correcao'
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps({'model':'clef-fixture','answers':{'classificacao':{'type':'choice','confidence':1.0,'choice':label,'probabilities':{k:float(k==label) for k in labels}}}}).encode())
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();home=root/'home';home.mkdir();work=root/'work'
                db=sqlite3.connect(home/'state.db')
                db.executescript('CREATE TABLE sessions(id TEXT,source TEXT,title TEXT);CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL);')
                db.execute('INSERT INTO sessions VALUES (?,?,?)',('synthetic','cli','Fixture'))
                db.executemany('INSERT INTO messages VALUES (?,?,?,?,?)',[(1,'synthetic','assistant','Relatório enviado.',1794000000),(2,'synthetic','user','Não, sua resposta ficou errada.',1794000010)])
                db.commit();db.close()
                key=root/'client.key';key.write_text('synthetic-client',encoding='utf-8');os.chmod(key,0o600)
                argv=['feedback-all','--home',str(home),'--work',str(work),'--allow-relay','--base-url',f'http://127.0.0.1:{server.server_port}/v1','--key-file',str(key),'--cutoff','2026-11-21']
                code,out,err=self.invoke(argv)
                self.assertEqual(code,0,err)
                result=json.loads(out)
                self.assertEqual(result['raw_records'],1)
                self.assertEqual(len(calls),2)
                dashboard=Path(result['dashboard'])
                self.assertTrue(dashboard.is_file())
                page=dashboard.read_text(encoding='utf-8')
                self.assertIn('Mediana',page)
                self.assertIn('Mensagens únicas',page)
                self.assertIn('Alcance do histórico disponível',page)
                self.assertNotIn('Não, sua resposta ficou errada.',page)
                self.assertNotIn('synthetic-client',page)
                self.assertNotIn(str(home),page)
                before_gets=len(gets)
                evidence=[work/'corpus.json',work/'satisfaction/analysis/results.jsonl',work/'corrections/analysis/results.jsonl']
                evidence_bytes={p:p.read_bytes() for p in evidence}
                with patch('selection.extract_selected',side_effect=AssertionError('frozen_snapshot_no_reread')):
                    code,out,err=self.invoke(argv)
                self.assertEqual(code,0,err)
                self.assertEqual({p:p.read_bytes() for p in evidence},evidence_bytes)
                self.assertEqual(len(calls),2)
                self.assertEqual(len(gets),before_gets)
                with patch('cli.configured_client',side_effect=AssertionError('offline')):
                    code,out,err=self.invoke(['feedback-report','--work',str(work)])
                self.assertEqual(code,0,err)
                with patch('feedback_report.ZoneInfo',side_effect=AssertionError('no_iana_database')), patch('cli.configured_client',side_effect=AssertionError('offline')):
                    code,out,err=self.invoke(['feedback-report','--work',str(work),'--timezone','UTC'])
                self.assertEqual(code,0,err)
                self.assertEqual(json.loads((work/'unique/report.json').read_text(encoding='utf-8'))['timezone'],'UTC')
                frozen=(work/'corpus.json').read_bytes()
                code,_,err=self.invoke(argv+['--model','different-model'])
                self.assertEqual(code,2)
                self.assertIn('campaign_mismatch',err)
                self.assertEqual((work/'corpus.json').read_bytes(),frozen)
                self.assertEqual(len(calls),2)
        finally:
            server.shutdown();thread.join();server.server_close()


if __name__=='__main__':unittest.main()
