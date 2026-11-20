"""Contrato offline: somente HOME temporário e SQLite sintético."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import extractor
import selection


class SelectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / 'home'
        self.home.mkdir()

    def file(self, name, text):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def database(self, rows=(), sessions=(('s', 'cli', 'Título'),)):
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, title TEXT)')
            db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)')
            db.executemany('INSERT INTO sessions VALUES (?,?,?)', sessions)
            db.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', rows)

    def test_docs_only_nao_exige_db_nem_explora_fonte_nao_selecionada(self):
        self.file('skills/a/SKILL.md', '# Método\nRevisar')
        (self.home / 'memories').symlink_to(self.home / 'ausente')
        result = selection.extract_selected(self.home, sources=('skills',))
        self.assertEqual([i['kind'] for i in result['items']], ['skill'])
        self.assertEqual(result['coverage']['status'], 'ok')
        self.assertEqual(result['coverage']['source_counts'], {'skills': 1})
        self.assertEqual(result['selection']['sources'], ['skills'])
        self.assertEqual(result['coverage']['sources_read'], ['skills/a/SKILL.md'])

    def test_feedback_contextual_ordenado_por_id_e_isolado_por_sessao(self):
        self.database([(7, 's', 'user', '  Corrija integralmente\n', 0),
                       (2, 's', 'assistant', 'Resposta imediata', 90),
                       (3, 'outro', 'assistant', 'Outra conversa', 1),
                       (4, 's', 'tool', 'Ferramenta privada', 1),
                       (5, 's', 'system', 'Sistema privado', 1),
                       (6, 's', 'reasoning', 'Pensamento privado', 1),
                       (1, 's', 'user', 'Pedido inicial', 99)],
                      sessions=(('s', 'cli', 'Título'), ('outro', 'cli', 'Outro')))
        result = selection.extract_selected(self.home, sources=('feedback',))
        self.assertEqual([i['text'] for i in result['items']],
                         ['Pedido inicial', '  Corrija integralmente\n'])
        first, item = result['items']
        self.assertEqual(first['kind'], 'feedback')
        self.assertTrue(first['context_missing'])
        self.assertEqual(item['context'], 'Resposta imediata')
        self.assertFalse(item['context_missing'])
        self.assertFalse(item['context_truncated'])
        self.assertEqual(item['provenance'][0],
                         {'path': 'state.db', 'session_id': 's', 'message_id': 7,
                          'timestamp': 0.0, 'previous_assistant_message_id': 2})
        public = json.dumps(result, ensure_ascii=False)
        self.assertTrue(all(t not in public for t in
                            ('Outra conversa', 'Ferramenta privada', 'Sistema privado', 'Pensamento privado')))
    def test_argumentos_invalidos_falham_antes_de_io(self):
        invalid = ({'sources': ('outro',)}, {'sources': 'tasks'},
                   {'session_ids': 's'}, {'session_ids': (1,)},
                   {'delegation': 'unknown'}, {'context_chars': -1},
                   {'context_chars': True}, {'context_chars': 1.5})
        with patch.object(selection, '_documents', side_effect=AssertionError('IO indevido')):
            for index, kwargs in enumerate(invalid):
                with self.subTest(case=index), self.assertRaises(ValueError):
                    selection.extract_selected(self.home, **kwargs)

    def test_contexto_limitado_ate_1200_com_flags_e_sem_cortar_texto_atual(self):
        self.database([(1, 's', 'assistant', 'A' * 1300, 1),
                       (2, 's', 'user', 'Texto ' * 300, 2)])
        for requested, expected in ((5000, 1200), (12, 12), (0, 0)):
            with self.subTest(limit=requested):
                result = selection.extract_selected(self.home, sources=('feedback',), context_chars=requested)
                item = result['items'][0]
                self.assertEqual(len(item['context']), expected)
                self.assertTrue(item['context_truncated'])
                self.assertFalse(item['context_missing'])
                self.assertEqual(item['text'], 'Texto ' * 300)
                self.assertEqual(result['selection']['context_chars'], expected)

    def test_home_symlink_recusado_sem_ler_fontes(self):
        self.file('skills/a/SKILL.md', 'Conteúdo não autorizado via alias')
        alias = self.home.parent / 'alias'
        alias.symlink_to(self.home, target_is_directory=True)
        result = selection.extract_selected(alias, sources=('skills',))
        self.assertEqual(result['items'], [])
        self.assertEqual(result['coverage']['failures'][0]['code'], 'symlink_rejected')

    def test_whitelist_exata_e_delegacao_antes_da_carga_textual(self):
        huge = 'X' * (extractor.MAX_FILE_BYTES + 1)
        self.database([(1, 's', 'user', 'Permitido', 1),
                       (2, 's-extra', 'user', huge, 2),
                       (3, 'S', 'assistant', huge, 3),
                       (4, 'child', 'user', huge, 4)],
                      sessions=(('s', 'cli', ''), ('s-extra', 'cli', ''),
                                ('S', 'cli', ''), ('child', 'subagent', '')))
        result = selection.extract_selected(self.home, sources=('feedback',), session_ids=('s',))
        self.assertEqual([i['text'] for i in result['items']], ['Permitido'])
        self.assertEqual(result['coverage']['messages_by_role'], {'user': 1})
        self.assertEqual(result['coverage']['failures'], [])
        result = selection.extract_selected(self.home, sources=('feedback',),
                                            session_ids=('child',), delegation='human')
        self.assertEqual(result['coverage']['messages_by_role'], {})
        self.assertEqual(result['coverage']['status'], 'ok')
        result = selection.extract_selected(self.home, sources=('feedback',), session_ids=('s%',))
        self.assertEqual(result['items'], [])

    def test_delegation_all_inclui_subagentes_marcados(self):
        self.database([(1, 's', 'user', 'Humano', 1), (2, 'c', 'user', 'Delegado', 2)],
                      sessions=(('s', 'cli', ''), ('c', 'subagent', '')))
        for mode, expected in (('all', [False, True]), ('human', [False]), ('subagent', [True])):
            with self.subTest(mode=mode):
                result = selection.extract_selected(self.home, sources=('feedback',), delegation=mode)
                self.assertEqual([i['delegated'] for i in result['items']], expected)

    def test_tasks_preserva_contrato_legado_e_feedback_nao_deduplica(self):
        self.database([(1, 's', 'user', 'Pedido', 1), (2, 's', 'user', 'Pedido', 1),
                       (3, 's', 'assistant', 'Resposta não usada por tasks', 3)])
        expected = extractor.extract(self.home)['items']
        result = selection.extract_selected(self.home)
        self.assertEqual(result['items'], expected)
        self.assertEqual(result['coverage']['source_counts'], {'tasks': 1, 'skills': 0, 'memories': 0})
        result = selection.extract_selected(self.home, sources=('tasks', 'feedback'))
        self.assertEqual(result['coverage']['source_counts'], {'tasks': 1, 'feedback': 2})

    def test_wrappers_vazios_e_blob_excluidos_sem_perder_eventos(self):
        rows = [(n, 's', 'user', '  ' + wrapper + ' teste]', n)
                for n, wrapper in enumerate(extractor.WRAPPERS, 1)]
        rows += [(6, 's', 'user', '', 6), (7, 's', 'user', b'blob', 7),
                 (8, 's', 'user', 'Entendi, obrigado', None),
                 (9, 's', 'user', 'Entendi, obrigado', None)]
        self.database(rows)
        result = selection.extract_selected(self.home, sources=('feedback',))
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['coverage']['excluded'], {'automatic_wrapper': 5, 'empty_or_nontext': 2})
        self.assertNotEqual(result['items'][0]['id'], result['items'][1]['id'])

    def test_redaction_texto_contexto_proveniencia_e_selecao(self):
        secret = 'sk-' + 'A' * 32
        self.database([(1, secret, 'assistant', 'Bearer ' + secret, 1),
                       (2, secret, 'user', 'api_key=' + secret, 2)],
                      sessions=((secret, 'cli', secret),))
        result = selection.extract_selected(self.home, sources=('feedback',), session_ids=(secret,))
        self.assertTrue(secret not in json.dumps(result), 'Não expor segredo sintético')
        self.assertIn('[REDACTED]', result['items'][0]['context'])
        self.assertEqual(result['items'][0]['provenance'][0]['previous_assistant_message_id'], 1)

    def test_memories_only_nao_explora_skills_e_selecao_vazia_sem_io(self):
        self.file('MEMORY.md', '# A\nTexto\n## B\nOutro')
        (self.home / 'skills').symlink_to(self.home / 'ausente')
        result = selection.extract_selected(self.home, sources=('memories',))
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['coverage']['status'], 'ok')
        with patch.object(selection, '_database', side_effect=AssertionError('IO indevido')):
            result = selection.extract_selected(self.home, sources=())
        self.assertEqual(result['items'], [])
        self.assertEqual(result['coverage']['source_counts'], {})

    def test_limite_sql_rejeita_inteiros_grandes_e_contexto_ausente_rastreavel(self):
        huge = 'Z' * (extractor.MAX_FILE_BYTES + 1)
        self.database([(1, 's', 'assistant', 'Antiga', 1),
                       (2, 's', 'assistant', huge, 2),
                       (3, 's', 'user', huge, 3),
                       (4, 's', 'user', 'Atual', 4)])
        original = sqlite3.connect
        def connect(*args, **kwargs):
            db = original(*args, **kwargs)
            def text(raw):
                self.assertLessEqual(len(raw), extractor.MAX_FILE_BYTES, 'SQL não deve carregar texto enorme')
                return raw.decode('utf-8')
            db.text_factory = text
            return db
        with patch.object(selection.sqlite3, 'connect', side_effect=connect):
            result = selection.extract_selected(self.home, sources=('feedback',))
        self.assertEqual([f['code'] for f in result['coverage']['failures']],
                         ['context_too_large', 'message_too_large'])
        item = result['items'][0]
        self.assertTrue(item['context_missing'])
        self.assertEqual(item['context'], '')
        self.assertEqual(item['provenance'][0]['previous_assistant_message_id'], 2)

    def test_banco_ausente_invalido_schema_e_sidecars_com_erros_seguros(self):
        result = selection.extract_selected(self.home, sources=('feedback',))
        self.assertEqual(result['coverage']['failures'][0]['code'], 'database_missing')
        path = self.file('state.db', 'Inválido privado')
        result = selection.extract_selected(self.home, sources=('tasks',))
        self.assertEqual(result['coverage']['failures'][0]['code'], 'database_read_error')
        self.assertNotIn('Inválido privado', json.dumps(result))
        path.unlink()
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE messages(id INTEGER)')
        result = selection.extract_selected(self.home, sources=('feedback',))
        self.assertEqual(result['coverage']['failures'][0]['code'], 'schema_required')
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = self.home / ('state.db' + suffix)
            sidecar.symlink_to(self.home / 'ausente')
            result = selection.extract_selected(self.home, sources=('tasks',))
            self.assertEqual(result['coverage']['failures'][0]['code'], 'symlink_rejected')
            sidecar.unlink()

    def test_sqlite_ro_query_only_fechado_preserva_bytes_e_inventario(self):
        self.database([(1, 's', 'user', 'Texto', 1)])
        before = {p.name: p.read_bytes() for p in self.home.iterdir()}
        original, connections = sqlite3.connect, []
        class Checked(sqlite3.Connection):
            closed = False
            checked = False
            def execute(conn, sql, *args):
                result = super(Checked, conn).execute(sql, *args)
                if sql == 'BEGIN':
                    self.assertEqual(super(Checked, conn).execute('PRAGMA query_only').fetchone()[0], 1)
                    with self.assertRaises(sqlite3.OperationalError):
                        super(Checked, conn).execute('DELETE FROM messages')
                    conn.checked = True
                return result
            def close(conn):
                conn.closed = True
                return super(Checked, conn).close()
        def connect(database, **kwargs):
            self.assertIn('mode=ro', database)
            self.assertNotIn('immutable', database)
            conn = original(database, factory=Checked, **kwargs)
            connections.append(conn)
            return conn
        with patch.object(selection.sqlite3, 'connect', side_effect=connect):
            result = selection.extract_selected(self.home, sources=('feedback',))
        self.assertEqual(result['coverage']['status'], 'ok')
        self.assertTrue(connections[0].closed and connections[0].checked)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.home.iterdir()})

    def test_wal_real_le_dados_nao_checkpointados_sem_alterar_db_canonico(self):
        self.database()
        path = self.home / 'state.db'
        with closing(sqlite3.connect(path)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            before = path.read_bytes()
            writer.execute("INSERT INTO messages VALUES (1,'s','user','Somente WAL',1)")
            writer.commit()
            self.assertEqual(path.read_bytes(), before)
            self.assertGreater((self.home / 'state.db-wal').stat().st_size, 0)
            result = selection.extract_selected(self.home, sources=('feedback',))
            self.assertEqual(result['coverage']['status'], 'ok')
            self.assertEqual([i['text'] for i in result['items']], ['Somente WAL'])
            self.assertEqual(path.read_bytes(), before)
            # No writes through the reader: the live writer remains usable.
            self.assertEqual(writer.execute('SELECT count(*) FROM messages').fetchone()[0], 1)

    def test_schema_minimo_sem_timestamp_preserva_cada_evento(self):
        with closing(sqlite3.connect(self.home / 'state.db')) as db, db:
            db.execute('CREATE TABLE sessions(id TEXT)')
            db.execute('CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT)')
            db.execute("INSERT INTO sessions VALUES ('s')")
            db.executemany('INSERT INTO messages VALUES (?,?,?,?)',
                           [(1, 's', 'assistant', 'Resposta'), (2, 's', 'user', 'Texto'),
                            (3, 's', 'assistant', ''), (4, 's', 'user', 'Texto')])
        result = selection.extract_selected(self.home, sources=('tasks', 'feedback'))
        self.assertEqual(result['coverage']['source_counts'], {'tasks': 2, 'feedback': 2})
        first, second = [i for i in result['items'] if i['kind'] == 'feedback']
        self.assertEqual(first['context'], 'Resposta')
        self.assertTrue(second['context_missing'])
        self.assertIsNone(second['provenance'][0]['timestamp'])
        self.assertEqual(second['provenance'][0]['previous_assistant_message_id'], 3)
        self.assertEqual(selection.extract_selected(self.home, sources=('feedback',),
                                                    delegation='subagent')['items'], [])

    def test_filtragem_sql_nao_converte_textos_de_fora_da_whitelist(self):
        self.database([(1, 's', 'user', 'Permitido', 1),
                       (2, 'S', 'user', 'Nunca carregar', 2),
                       (3, 's', 'tool', 'Nunca carregar', 3),
                       (4, 's', 'system', 'Nunca carregar', 4),
                       (5, 's', 'reasoning', 'Nunca carregar', 5)],
                      sessions=(('s', 'cli', ''), ('S', 'cli', 'Nunca carregar')))
        original = sqlite3.connect
        def connect(*args, **kwargs):
            db = original(*args, **kwargs)
            def text(raw):
                self.assertFalse(b'Nunca carregar' in raw, 'Texto fora de escopo carregado')
                return raw.decode('utf-8')
            db.text_factory = text
            return db
        with patch.object(selection.sqlite3, 'connect', side_effect=connect):
            result = selection.extract_selected(self.home, sources=('feedback',), session_ids=('s',))
        self.assertEqual(result['coverage']['status'], 'ok')
        self.assertEqual(len(result['items']), 1)

    def test_fontes_documentais_falhas_e_exclusoes(self):
        self.file('skills/a/SKILL.md', 'Bom')
        self.file('skills/a/config.md', 'Não ler configuração')
        self.file('skills/a/references/guia.txt', 'Referência')
        self.file('skills/a/scripts/run.py', 'Não executar')
        self.file('skills/b/SKILL.md', 'X' * (extractor.MAX_FILE_BYTES + 1))
        self.file('skills/c/SKILL.md', '').write_bytes(b'\xff')
        (self.home / 'skills' / 'alias').symlink_to(self.home / 'ausente')
        result = selection.extract_selected(self.home, sources=('skills',))
        self.assertEqual(len(result['items']), 2)
        self.assertEqual({f['code'] for f in result['coverage']['failures']},
                         {'file_too_large', 'invalid_utf8', 'symlink_rejected'})
        self.assertNotIn('Não ler', json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
