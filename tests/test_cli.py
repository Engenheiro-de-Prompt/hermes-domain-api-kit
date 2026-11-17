import contextlib
import io
import tempfile
import unittest
from pathlib import Path
import cli

class CliTests(unittest.TestCase):
    def test_invalid_arguments_exit_with_static_error_without_echo(self):
        import uuid
        token='synthetic_'+uuid.uuid4().hex
        cases=(['models','--'+token], ['models','--timeout',token],
               ['run','--limit',token], [token])
        for index,argv in enumerate(cases):
            with self.subTest(case=index):
                out=io.StringIO();err=io.StringIO()
                with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                    with self.assertRaises(SystemExit) as raised:
                        cli.main(argv)
                self.assertTrue(raised.exception.code==2,'invalid arguments must exit 2')
                self.assertTrue(token not in out.getvalue()+err.getvalue(),'argument content must not be echoed')
                self.assertTrue(out.getvalue()=='','invalid arguments must not write stdout')
                self.assertTrue(err.getvalue()=='{"error": "invalid_arguments"}\n','invalid arguments must use the static error')

    def test_help_exits_zero_with_usage_on_stdout(self):
        out=io.StringIO();err=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                cli.main(['--help'])
        self.assertTrue(raised.exception.code==0,'help must exit 0')
        self.assertTrue('usage:' in out.getvalue(),'help must display usage')
        self.assertTrue('--timeout' in out.getvalue(),'help must display options')
        self.assertTrue(err.getvalue()=='','help must not write stderr')

    def test_run_requires_explicit_relay_authorization_before_key_or_http(self):
        with tempfile.TemporaryDirectory() as t:
            err=io.StringIO()
            with contextlib.redirect_stderr(err):
                code=cli.main(['run','--work',t,'--base-url','https://example.invalid/api/public/v1','--key-file',str(Path(t)/'absent')])
            self.assertEqual(code,2)
            self.assertIn('relay_consent_required',err.getvalue())
            self.assertFalse((Path(t)/'classification').exists())

    def test_extract_creates_frozen_private_snapshot_without_network(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/'hermes';home.mkdir()
            db=sqlite3.connect(home/'state.db')
            db.executescript('CREATE TABLE sessions(id TEXT,source TEXT,title TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL);')
            db.execute('INSERT INTO sessions VALUES (?,?,?)',('s','cli','Sintético'))
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(1,'s','user','Planeje minhas férias em família.',1.0)); db.commit();db.close()
            work=Path(t)/'work'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['extract','--home',str(home),'--work',str(work)]),0)
            self.assertTrue((work/'corpus.json').exists())
            import json
            data=json.loads((work/'corpus.json').read_text())
            self.assertEqual(len(data['items']),1)
            self.assertEqual(data['items'][0]['kind'],'task')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['extract','--home',str(home),'--work',str(work)]),2)

    def test_run_exercises_real_http_contract_and_resume(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from study import save_json, digest
        from synthetic import items
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                data=json.dumps({'data':[{'id':'clef-fixture','task':'classification'}]}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(data)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(body)
                labels=('pessoal','profissional','misto','compartilhado','indeterminado')
                data=json.dumps({'model':'clef-fixture','answers':{'dominio':{'choice':'pessoal','probabilities':{l:float(l=='pessoal') for l in labels}}}}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(data)
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as t:
                work=Path(t)/'work'; corpus={'items':items()[:1],'coverage':{}}
                corpus['items_sha256']=digest(corpus['items']);save_json(work/'corpus.json',corpus)
                key=Path(t)/'key';key.write_text('synthetic-client')
                argv=['run','--work',str(work),'--base-url',f'http://127.0.0.1:{server.server_port}/v1','--model','clef-fixture','--key-file',str(key),'--allow-relay']
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(argv),0)
                    self.assertTrue((work/'classification/summary.json').exists())
                    self.assertEqual(cli.main(argv),0)
                self.assertEqual(len(calls),1)
                self.assertEqual(calls[0]['keep_alive'],0)
                verify_args=['verify','--work',str(Path(t)/'verify'),'--base-url',f'http://127.0.0.1:{server.server_port}/v1','--model','clef-fixture','--key-file',str(key)]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(verify_args),1)
                report=json.loads((Path(t)/'verify/verification/result.json').read_text())
                self.assertFalse(report['all_expected_labels_matched'])
                self.assertEqual(report['total'],5)
                self.assertEqual(report['matched'],1)
        finally:server.shutdown();server.server_close();thread.join()

    def test_incomplete_extraction_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t)/'empty';home.mkdir();work=Path(t)/'work'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['extract','--home',str(home),'--work',str(work)]),1)
            self.assertTrue((work/'corpus.json').exists())
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(['run','--work',str(work),'--allow-relay']),2)
            self.assertIn('incomplete_corpus',error.getvalue())

if __name__=='__main__':unittest.main()
