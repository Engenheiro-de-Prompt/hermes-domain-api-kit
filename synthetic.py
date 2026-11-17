"""Dados SOMENTE sintéticos; nenhum conteúdo de usuários reais."""
from pathlib import Path
import hashlib
import sqlite3

CASES=[
 ('pessoal','task','Quero planejar minhas férias em família e organizar meu orçamento doméstico.'),
 ('profissional','task','Meu cliente contratou uma entrega de software para a empresa dele; preciso preparar a proposta comercial.'),
 ('misto','task','Preciso revisar meu orçamento doméstico e, em outra tarefa, preparar a proposta comercial para meu cliente.'),
 ('compartilhado','skill','Procedimento genérico reutilizável: verificar evidências e testar uma alteração antes de afirmar que funcionou.'),
 ('indeterminado','task','Instale esse aplicativo no computador. Não foi informada sua finalidade de uso.')]


def items():
    return [{'id':hashlib.sha256(text.encode()).hexdigest(),'kind':kind,'text':text,'context':'','provenance':[], 'delegated':False} for expected,kind,text in CASES]


def create_home(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    db=sqlite3.connect(directory/'state.db')
    db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY,source TEXT,title TEXT); CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,timestamp REAL);')
    db.execute('INSERT INTO sessions VALUES (?,?,?)',('synthetic-session','cli','Classificação sintética'))
    for index,(expected,kind,text) in enumerate(CASES):
        if kind=='task':db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(index+1,'synthetic-session','user',text,float(index+1)))
    db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(90,'synthetic-session','assistant','Resposta sintética excluída.',90.0))
    db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(91,'synthetic-session','tool','Resultado sintético excluído.',91.0))
    db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(92,'synthetic-session','user','[ASYNC DELEGATION BATCH COMPLETE] aviso automático excluído.',92.0))
    db.commit();db.close()
    skill=directory/'skills/synthetic';skill.mkdir(parents=True)
    (skill/'SKILL.md').write_text(CASES[3][2],encoding='utf-8')
    memory=directory/'memories';memory.mkdir()
    (memory/'USER.md').write_text('Prefiro jogar como passatempo pessoal com minha família.',encoding='utf-8')
    return directory

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description='Cria home Hermes somente sintético em diretório inexistente.')
    p.add_argument('destination');args=p.parse_args();create_home(args.destination)
    print('synthetic_home_created')
