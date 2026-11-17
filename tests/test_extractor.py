"""Fixtures sintéticas: nenhum acesso ao histórico instalado."""
import json
import os
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import extractor


class ExtratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'hermes'
        self.home.mkdir()

    def banco(self, rows=(), optional=True):
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY' +
                       (', source TEXT, title TEXT' if optional else '') + ')')
            db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT' +
                       (', timestamp REAL' if optional else '') + ')')
            if optional:
                db.execute("INSERT INTO sessions VALUES ('s', 'cli', 'Planejamento')")
            else:
                db.execute("INSERT INTO sessions VALUES ('s')")
            for row in rows:
                marks = ','.join('?' for _ in row)
                db.execute('INSERT INTO messages VALUES (' + marks + ')', row)

    def test_extrai_somente_pedidos_sem_alterar_banco(self):
        self.banco([(1, 's', 'user', 'Planejar entrega', 1),
                    (2, 's', 'assistant', 'Raciocínio privado', 2),
                    (3, 's', 'tool', 'Saída privada', 3),
                    (4, 's', 'system', 'Prompt privado', 4)])
        antes = (self.home / 'state.db').read_bytes()
        result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 1)
        item = result['items'][0]
        self.assertEqual(item['text'], 'Planejar entrega')
        self.assertEqual(item['kind'], 'task')
        self.assertFalse(item['delegated'])
        self.assertEqual(item['provenance'][0]['path'], 'state.db')
        self.assertEqual(result['coverage']['messages_by_role'],
                         {'user': 1, 'assistant': 1, 'tool': 1, 'system': 1})
        self.assertEqual(antes, (self.home / 'state.db').read_bytes())
        self.assertEqual(result, extractor.extract(self.home))
        self.assertNotIn('privado', json.dumps(result, ensure_ascii=False))

    def test_dedup_preserva_referencias_e_eventos_distintos(self):
        rows = [(1, 's', 'user', 'Mesmo pedido', 1),
                (2, 's', 'user', 'Mesmo pedido', 1),
                (3, 's', 'user', 'Mesmo pedido', 2)]
        self.banco(rows)
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute("UPDATE sessions SET source='subagent'")
        result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(len(result['items'][0]['provenance']), 2)
        self.assertTrue(all(item['delegated'] for item in result['items']))
        self.assertNotEqual(result['items'][0]['id'], result['items'][1]['id'])
        self.assertEqual(result['coverage']['excluded']['duplicate'], 1)

    def test_wrappers_nao_sao_pedidos(self):
        prefixes = ['[CONTEXT COMPACTION', '[ASYNC', '[Your active',
                    '[IMPORTANT:', '[INTERNAL NOTIFICATION']
        self.banco([(i, 's', 'user', '  ' + prefix + ' teste]', i)
                    for i, prefix in enumerate(prefixes, 1)] +
                   [(9, 's', 'user', 'Explique [ASYNC em texto normal', 9)])
        result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['coverage']['excluded']['automatic_wrapper'], 5)

    def test_opcionais_ausentes_nao_colapsam_eventos(self):
        self.banco([(1, 's', 'user', 'Repetir'), (2, 's', 'user', 'Repetir')], optional=False)
        result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['coverage']['status'], 'ok')
        self.assertTrue(all(item['context'] == '' for item in result['items']))

    def test_erros_db_explicitos_sem_conteudo(self):
        result = extractor.extract(self.home)
        self.assertEqual(result['coverage']['status'], 'error')
        self.assertEqual(result['coverage']['failures'][0]['code'], 'database_missing')
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('CREATE TABLE messages (id INTEGER, content TEXT)')
        result = extractor.extract(self.home)
        self.assertEqual(result['coverage']['status'], 'error')
        self.assertEqual(result['coverage']['failures'][0]['code'], 'schema_required')
        (self.home / 'state.db').write_bytes(b'arquivo invalido')
        result = extractor.extract(self.home)
        self.assertEqual(result['coverage']['failures'][0]['code'], 'database_read_error')
        self.assertNotIn('arquivo invalido', json.dumps(result))

    def arquivo(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_skills_referencias_e_memorias_em_secoes(self):
        self.banco()
        self.arquivo('skills/exemplo/SKILL.md', '# Procedimento\nExecutar revisão.')
        for suffix in ('md', 'txt', 'yaml', 'json', 'py'):
            self.arquivo('skills/exemplo/references/guia.' + suffix, 'Conteúdo ' + suffix)
        self.arquivo('skills/exemplo/templates/modelo.txt', 'Modelo textual')
        self.arquivo('skills/exemplo/scripts/nao_executar.py', "raise RuntimeError('nunca executar')")
        self.arquivo('memories/MEMORY.md', '# Preferências\nTexto A\n\n## Rotina\nTexto B')
        self.arquivo('memories/USER.md', 'Parte C\n§ Parte D')
        self.arquivo('MEMORY.md', 'Raiz E')
        self.arquivo('USER.md', 'Raiz F')
        self.arquivo('profiles/outro/skills/privado/SKILL.md', 'Não explorar')
        self.arquivo('memories/outro.md', 'Não explorar')
        self.arquivo('config.yaml', 'Não explorar')
        result = extractor.extract(self.home)
        skills = [x for x in result['items'] if x['kind'] == 'skill']
        memories = [x for x in result['items'] if x['kind'] == 'memory']
        self.assertEqual(len(skills), 7)
        self.assertEqual(len(memories), 6)
        self.assertTrue(all(x['text'].strip() for x in memories))
        self.assertTrue(all(not Path(x['provenance'][0]['path']).is_absolute()
                            for x in result['items']))
        self.assertNotIn('Não explorar', json.dumps(result, ensure_ascii=False))
        self.assertEqual(result, extractor.extract(self.home))

    def test_symlinks_e_fontes_sensiveis_nao_sao_lidos(self):
        self.banco()
        external = Path(self.tmp.name) / 'externo'
        external.mkdir()
        (external / 'SKILL.md').write_text('Segredo externo', encoding='utf-8')
        self.arquivo('skills/bom/SKILL.md', 'Seguro')
        (self.home / 'skills' / 'link').symlink_to(external, target_is_directory=True)
        (self.home / 'skills' / 'bom' / 'ref.md').symlink_to(external / 'SKILL.md')
        for name in ('auth.md', 'config.md', '.env.md', 'system_prompt.md', 'reasoning.md'):
            self.arquivo('skills/bom/' + name, 'Não ler sensível')
        result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 1)
        self.assertNotIn('Segredo externo', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('Não ler sensível', json.dumps(result, ensure_ascii=False))
        self.assertGreaterEqual(len(result['coverage']['failures']), 2)
        (self.home / 'state.db').unlink()
        with closing(sqlite3.connect(external / 'state.db')) as db, db:
            db.execute('CREATE TABLE proibida (id INTEGER)')
        (self.home / 'state.db').symlink_to(external / 'state.db')
        self.assertEqual(extractor.extract(self.home)['coverage']['failures'][0]['code'], 'symlink_rejected')

    def test_arquivo_enorme_e_utf8_invalido_falham_sem_truncar(self):
        self.banco()
        self.arquivo('skills/a/SKILL.md', 'X' * 3000000)
        path = self.arquivo('skills/b/SKILL.md', '')
        path.write_bytes(b'\xff\xfe')
        result = extractor.extract(self.home)
        self.assertEqual(result['items'], [])
        self.assertEqual({x['code'] for x in result['coverage']['failures']},
                         {'file_too_large', 'invalid_utf8'})
        self.assertEqual(result['coverage']['status'], 'error')

    def test_redaction_em_todas_superficies_de_saida(self):
        secrets = ['sk-' + 'A' * 32, 'hf_' + 'B' * 32, 'ghp_' + 'C' * 36,
                   'AIza' + 'D' * 35, 'valor-sintetico-chave', 'credencial-bearer-sintetica']
        payload = '\n'.join(secrets[:4]) + '\napi_key="' + secrets[4] + '"\nAuthorization: Bearer ' + secrets[5]
        self.banco([(1, 's', 'user', payload, 1)])
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('UPDATE sessions SET id=?, title=?', (secrets[0], payload))
            db.execute('UPDATE messages SET session_id=?', (secrets[0],))
        self.arquivo('skills/' + secrets[1] + '/SKILL.md', payload)
        self.arquivo('MEMORY.md', payload)
        result = extractor.extract(self.home)
        public = json.dumps(result, ensure_ascii=False)
        self.assertTrue(all(secret not in public for secret in secrets), 'Saída deve estar sanitizada')
        self.assertIn('[REDACTED]', public)
        self.assertEqual(len(result['items']), 3)

    def test_contexto_limitado_sem_respostas_ou_raciocinio(self):
        self.banco([(1, 's', 'user', 'Pedido', 1),
                    (2, 's', 'assistant', 'Nao usar resposta', 2)])
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('UPDATE sessions SET title=?', ('T' * 2000,))
        result = extractor.extract(self.home)
        self.assertLessEqual(len(result['items'][0]['context']), 512)
        self.assertNotIn('Nao usar resposta', json.dumps(result))

    def test_mensagem_enorme_e_rejeitada_inteira(self):
        self.banco([(1, 's', 'user', 'X' * 3000000, 1),
                    (2, 's', 'user', 'Pedido pequeno', 2)])
        result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['text'], 'Pedido pequeno')
        self.assertEqual(result['coverage']['failures'][0]['code'], 'message_too_large')
        self.assertEqual(result['coverage']['messages_by_role']['user'], 2)

    def test_role_desconhecida_nao_vaza_no_relatorio(self):
        self.banco([(1, 's', 'papel-nao-confiavel', 'Conteudo descartado', 1)])
        result = extractor.extract(self.home)
        self.assertEqual(result['coverage']['messages_by_role'], {'other': 1})
        self.assertEqual(result['items'], [])
        self.assertNotIn('papel-nao-confiavel', json.dumps(result))

    def test_nao_le_prompts_de_sistema_ou_raciocinio_por_nome(self):
        self.banco()
        for name in ('SYSTEM.md', 'SOUL.md', 'AGENTS.md', 'prompts/sistema.md',
                     'chain_of_thought.md', 'thinking.md', 'authentication.md'):
            self.arquivo('skills/exemplo/' + name, 'Não ler prompt ou raciocínio')
        self.arquivo('skills/exemplo/SKILL.md', 'Procedimento permitido')
        result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 1)
        self.assertNotIn('Não ler prompt', json.dumps(result, ensure_ascii=False))

    def test_redaction_de_contexto_e_idempotente(self):
        self.banco([(1, 's', 'user', 'Pedido', 1)])
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('UPDATE sessions SET title=?', ('Authorization: Bearer ' + 'Z' * 24,))
        item = extractor.extract(self.home)['items'][0]
        self.assertTrue(item['context'].endswith('[REDACTED]'), 'Marcador de redaction único')
        self.assertNotIn('[REDACTED]]', item['context'])

    def test_sidecar_symlink_e_rejeitado(self):
        self.banco()
        external = Path(self.tmp.name) / 'externo'
        external.write_bytes(b'Nao abrir')
        (self.home / 'state.db-wal').symlink_to(external)
        result = extractor.extract(self.home)
        self.assertEqual(result['coverage']['status'], 'error')
        self.assertEqual(result['coverage']['failures'][0]['code'], 'symlink_rejected')

    def test_sqlite_real_aberto_ro_query_only_e_fechado(self):
        self.banco([(1, 's', 'user', 'Pedido', 1)])
        original = sqlite3.connect
        conexoes = []

        class ConexaoVerificada(sqlite3.Connection):
            fechada = False
            query_only_observado = False
            escrita_bloqueada = False

            def execute(conn, sql, *args, **kwargs):
                result = super(ConexaoVerificada, conn).execute(sql, *args, **kwargs)
                if sql == 'BEGIN':
                    conn.query_only_observado = bool(super(ConexaoVerificada, conn).execute(
                        'PRAGMA query_only').fetchone()[0])
                    try:
                        super(ConexaoVerificada, conn).execute("DELETE FROM messages")
                    except sqlite3.OperationalError:
                        conn.escrita_bloqueada = True
                return result

            def close(conn):
                conn.fechada = True
                return super(ConexaoVerificada, conn).close()

        def conectar(database, **kwargs):
            self.assertTrue(database.endswith('?mode=ro'))
            self.assertTrue(kwargs.get('uri'))
            conn = original(database, factory=ConexaoVerificada, **kwargs)
            conexoes.append(conn)
            return conn

        with patch.object(extractor.sqlite3, 'connect', side_effect=conectar):
            result = extractor.extract(self.home)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(len(conexoes), 1)
        self.assertTrue(conexoes[0].query_only_observado)
        self.assertTrue(conexoes[0].escrita_bloqueada)
        self.assertTrue(conexoes[0].fechada)

    def test_texto_e_fontes_textuais_preservados(self):
        self.banco([(1, 's', 'user', '  Pedido com acentos: revisão\n\n', 1)])
        path = self.arquivo('skills/portátil/SKILL.md', '  # Método\nRevisão\n\n')
        antes = path.read_bytes()
        result = extractor.extract(self.home)
        self.assertEqual(result['items'][0]['text'], '  Pedido com acentos: revisão\n\n')
        self.assertEqual(result['items'][1]['text'], antes.decode('utf-8'))
        self.assertEqual(path.read_bytes(), antes)

    def test_descoberta_respeita_prioridade(self):
        with patch.dict(os.environ, {'HERMES_HOME': str(self.home)}):
            self.assertEqual(extractor.discover_home(), self.home)
            self.assertEqual(extractor.discover_home(self.home / 'outro'), self.home / 'outro')
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=self.home):
            self.assertEqual(extractor.discover_home(), self.home / '.hermes')


if __name__ == '__main__':
    unittest.main()
