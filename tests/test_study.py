import json
import tempfile
import unittest
from pathlib import Path
import study

LABELS=('pessoal','profissional','misto','compartilhado','indeterminado')

def answer(label):
    return {'model':'classifier-test','answers':{'dominio':{'choice':label,'probabilities':{x:float(x==label) for x in LABELS}}}}

class Client:
    base_url='https://example.invalid/api/public/v1'
    def __init__(self): self.calls=[]
    def classify(self, model, state, questions):
        self.calls.append(json.loads(state))
        return answer('pessoal')

class StudyTests(unittest.TestCase):
    def item(self, text='Planejar férias em família.'):
        return {'id':'a','kind':'task','text':text,'context':'','provenance':[], 'delegated':False}
    def test_api_decision_reaches_exclusive_dataset_and_csv(self):
        with tempfile.TemporaryDirectory() as t:
            client=Client()
            s=study.classify_records([self.item()],client,'classifier-test',Path(t)/'run')
            self.assertEqual(s['by_category']['pessoal'],1)
            rows=[json.loads(x) for x in (Path(t)/'run/datasets/pessoal.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['text'],self.item()['text'])
            self.assertTrue(rows[0]['provisional'])
            self.assertEqual(len(client.calls),1)
            self.assertEqual(client.calls[0]['documento_para_classificar'],self.item()['text'])
            self.assertTrue((Path(t)/'run/dataset.csv').exists())

    def test_resume_keeps_first_error_and_does_not_repeat_requests(self):
        class Broken(Client):
            def classify(self,*args):
                self.calls.append('called')
                raise TimeoutError('do not expose remote text')
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'run'; c=Broken()
            first=study.classify_records([self.item()],c,'classifier-test',out)
            self.assertEqual(first['failed'],1)
            self.assertEqual(first['by_category']['indeterminado'],1)
            second=study.classify_records([self.item()],c,'classifier-test',out)
            self.assertEqual(len(c.calls),1)
            self.assertEqual(first,second)
            with self.assertRaisesRegex(ValueError,'campaign_mismatch'):
                study.classify_records([self.item('Different corpus')],c,'classifier-test',out)

    def test_long_item_preserves_tail_and_aggregates_both_purposes(self):
        class Mixed(Client):
            def classify(self,model,state,questions):
                self.calls.append(json.loads(state))
                return answer('pessoal' if len(self.calls)==1 else 'profissional')
        with tempfile.TemporaryDirectory() as t:
            c=Mixed(); text='P'*12+'T'*12
            out=Path(t)/'run'
            s=study.classify_records([self.item(text)],c,'classifier-test',out,chunk_chars=12)
            self.assertEqual(s['by_category']['misto'],1)
            self.assertEqual(''.join(x['documento_para_classificar'] for x in c.calls),text)
            self.assertEqual(len(c.calls),2)
            study.classify_records([self.item(text)],c,'classifier-test',out,chunk_chars=12)
            self.assertEqual(len(c.calls),2)

    def test_interrupted_checkpoint_remains_unknown_without_replay(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as t:
            c=Client();out=Path(t)/'run'
            study.classify_records([self.item()],c,'classifier-test',out)
            db=sqlite3.connect(out/'decisions.sqlite')
            db.execute("UPDATE decisions SET state='started',result=NULL");db.commit();db.close()
            result=study.classify_records([self.item()],c,'classifier-test',out)
            self.assertEqual(len(c.calls),1)
            self.assertEqual(result['failed'],1)
            row=json.loads((out/'datasets/indeterminado.jsonl').read_text())
            self.assertEqual(row['chunks'][0]['error_code'],'outcome_unknown')

if __name__=='__main__': unittest.main()
