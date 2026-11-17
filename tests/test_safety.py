"""Regressões de integração com tokens estritamente sintéticos."""
import tempfile
import sqlite3
import unittest
from pathlib import Path
import extractor

class SafetyTests(unittest.TestCase):
    def test_relay_client_and_agent_tokens_are_redacted_even_without_bearer(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);db=sqlite3.connect(home/'state.db')
            db.executescript('CREATE TABLE sessions(id TEXT); CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT);')
            db.execute('INSERT INTO sessions VALUES (?)',('s',))
            # Split literals prevent the test itself resembling a real provisioned token.
            values=['lr_'+'live_'+'SYNTHETIC12345678901234567890','lr_'+'agent_'+'SYNTHETIC12345678901234567890']
            db.execute('INSERT INTO messages VALUES (?,?,?,?)',(1,'s','user','Chaves de teste: '+ ' '.join(values)))
            db.commit();db.close()
            result=extractor.extract(home)
            output=result['items'][0]['text']
            self.assertTrue(all(v not in output for v in values),'known relay token not redacted')
            self.assertIn('[REDACTED]',output)

if __name__=='__main__':unittest.main()
