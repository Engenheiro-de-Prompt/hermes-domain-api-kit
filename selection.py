"""Seleção offline explícita de fontes Hermes, usando apenas a stdlib.

Cobertura é restrita à seleção, não atesta o perfil inteiro. Redaction por
formatos conhecidos não é anonimização. Não executa arquivos extraídos.
"""
from contextlib import closing
from pathlib import Path
import os
import sqlite3

import extractor as _e


SOURCES = ('tasks', 'feedback', 'skills', 'memories')


def _documents(home, sources, coverage, snapshot=None):
    """Descobre cada fonte separadamente, sem explorar a fonte não escolhida."""
    candidates = []
    if 'skills' in sources:
        root = home / 'skills'
        if _e._allowed_path(home, root, coverage) and root.is_dir():
            def walk_error(_error):
                _e._failure(coverage, 'skills', 'directory_read_error')
            for base, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
                dirs[:] = sorted(name for name in dirs
                                 if not _e._sensitive(Path(name)) and
                                 _e._allowed_path(home, Path(base) / name, coverage))
                for name in sorted(files):
                    path = Path(base) / name
                    relative = path.relative_to(root)
                    if _e._sensitive(relative):
                        _e._count(coverage['excluded'], 'sensitive_path')
                        continue
                    if not _e._allowed_path(home, path, coverage):
                        continue
                    if path.is_file() and (path.suffix.lower() == '.md' or
                            (path.suffix.lower() in {'.txt', '.yaml', '.json', '.py'} and
                             {'references', 'templates'} & set(relative.parts[:-1]))):
                        candidates.append((path, 'skill'))
    if 'memories' in sources:
        for relative in ('memories/MEMORY.md', 'memories/USER.md', 'MEMORY.md', 'USER.md'):
            path = home / relative
            if _e._allowed_path(home, path, coverage) and path.is_file():
                candidates.append((path, 'memory'))
    items = []
    for path, kind in candidates:
        relative = path.relative_to(home).as_posix()
        text = _e._read_document(path, relative, coverage)
        if text is None:
            continue
        if snapshot is not None:
            snapshot(('document', relative, text))
        coverage['sources_read'].append(relative)
        sections = _e._sections(text) if kind == 'memory' else [text]
        for index, section in enumerate(sections):
            if section.strip():
                items.append({'id': _e._hash(kind, relative, index, section),
                              'kind': kind, 'text': section, 'context': _e._context(relative),
                              'delegated': False,
                              'provenance': [{'path': relative, 'section': index}]})
    return items


def _database(home, sources, session_ids, delegation, context_chars, coverage, snapshot=None):
    """Consulta filtrada antes da projeção textual; nunca carrega tools/reasoning.

    mode=ro/query_only proíbem escrita de dados/esquema; BEGIN mantém uma
    leitura consistente, inclusive dos commits ainda presentes no WAL vivo.
    Sidecars regulares são aceitos; symlinks continuam recusados. SQLite pode
    criar/alterar WAL/SHM: isto NÃO promete uma aquisição forense sem escritas.
    """
    path = home / 'state.db'
    if not _e._allowed_path(home, path, coverage):
        return []
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = home / ('state.db' + suffix)
        if not _e._allowed_path(home, sidecar, coverage):
            return []

    if not path.is_file():
        _e._failure(coverage, 'state.db', 'database_missing')
        return []
    items, seen, previous = [], {}, {}
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            cols = {table: {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
                    for table in ('sessions', 'messages')}
            if not {'id'} <= cols['sessions'] or not {'id', 'session_id', 'role', 'content'} <= cols['messages']:
                _e._failure(coverage, 'state.db', 'schema_required')
                return []
            where, parameters = [], []
            if session_ids:
                where.append('m.session_id COLLATE BINARY IN (' + ','.join('?' for _ in session_ids) + ')')
                parameters.extend(session_ids)
            delegated = ("EXISTS (SELECT 1 FROM sessions s WHERE s.id COLLATE BINARY = m.session_id "
                         "AND s.source COLLATE BINARY = 'subagent')" if 'source' in cols['sessions'] else '0')
            if delegation != 'all':
                where.append(('' if delegation == 'subagent' else 'NOT ') + '(' + delegated + ')')
            # O título legado só é projetado para tasks, e também tem limite SQL.
            title = ("(SELECT CASE WHEN length(CAST(s.title AS BLOB)) <= " + str(_e.MAX_FILE_BYTES) +
                     " THEN s.title ELSE NULL END FROM sessions s "
                     "WHERE s.id COLLATE BINARY = m.session_id LIMIT 1)"
                     if 'tasks' in sources and 'title' in cols['sessions'] else 'NULL')
            stamp = 'm.timestamp' if 'timestamp' in cols['messages'] else 'NULL'
            roles = "('user','assistant')" if 'feedback' in sources else "('user')"
            query = ("SELECT m.id,m.session_id,m.role,CASE WHEN m.role IN " + roles +
                     " AND length(CAST(m.content AS BLOB)) <= ? THEN m.content ELSE NULL END," +
                     stamp + ",length(CAST(m.content AS BLOB))," + delegated + ',' + title +
                     ' FROM messages m' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY m.id')
            for mid, sid, role, text, timestamp, size, is_delegated, title_value in db.execute(
                    query, [_e.MAX_FILE_BYTES] + parameters):
                if snapshot is not None:
                    # Hash the entire authorized SQL projection before redaction,
                    # filtering/deduplication or context truncation, never tool text.
                    snapshot(('message', mid, sid, role, text, timestamp, size, is_delegated, title_value))
                label = role if role in ('user', 'assistant', 'tool', 'system') else 'other'
                _e._count(coverage['messages_by_role'], label)
                if role == 'assistant' and 'feedback' in sources:
                    if size is not None and size > _e.MAX_FILE_BYTES:
                        _e._failure(coverage, 'state.db', 'context_too_large')
                        previous[sid] = (mid, None)
                    else:
                        previous[sid] = (mid, text if isinstance(text, str) and text.strip() else None)
                if role != 'user':
                    _e._count(coverage['excluded'], 'non_user')
                    continue
                if size is not None and size > _e.MAX_FILE_BYTES:
                    _e._failure(coverage, 'state.db', 'message_too_large')
                    _e._count(coverage['excluded'], 'message_too_large')
                    continue
                if not isinstance(text, str) or not text.strip():
                    _e._count(coverage['excluded'], 'empty_or_nontext')
                    continue
                if text.lstrip().startswith(_e.WRAPPERS):
                    _e._count(coverage['excluded'], 'automatic_wrapper')
                    continue
                ref = {'path': 'state.db', 'session_id': sid, 'message_id': mid, 'timestamp': timestamp}
                if 'tasks' in sources:
                    event = timestamp if timestamp is not None else ('message', mid)
                    identity = _e._hash('task', sid, role, event, _e._hash(text))
                    if identity in seen:
                        seen[identity]['provenance'].append(dict(ref))
                        _e._count(coverage['excluded'], 'duplicate')
                    else:
                        item = {'id': identity, 'kind': 'task', 'text': text,
                                'context': _e._context(title_value), 'delegated': bool(is_delegated),
                                'provenance': [dict(ref)]}
                        seen[identity] = item
                        items.append(item)
                if 'feedback' in sources:
                    prior_id, prior_text = previous.get(sid, (None, None))
                    context = _e._redact(prior_text) if prior_text is not None else ''
                    ref['previous_assistant_message_id'] = prior_id
                    items.append({'id': _e._hash('feedback', sid, mid), 'kind': 'feedback',
                                  'text': text, 'context': context[:context_chars],
                                  'context_missing': prior_text is None,
                                  'context_truncated': len(context) > context_chars,
                                  'delegated': bool(is_delegated), 'provenance': [ref]})
    except (sqlite3.Error, OSError, ValueError):
        _e._failure(coverage, 'state.db', 'database_read_error')
        return []
    coverage['sources_read'].append('state.db')
    return items


def extract_selected(home, *, sources=('tasks', 'skills', 'memories'),
                     session_ids=(), delegation='all', context_chars=1200, snapshot=None):
    """Retorna {items, coverage, selection}; argumentos inválidos geram ValueError.

    sources=() não lê fontes. session_ids=() significa todas as sessões;
    demais IDs são whitelist exata (sem prefixos/globs), antes da carga textual.
    delegation afeta somente mensagens: all inclui subagentes com delegated=True,
    human os exclui, subagent os restringe. Documentos não pertencem a sessões.
    Feedback preserva cada evento user não-wrapper, sem deduplicar nem inferir
    insatisfação. O contexto é a última resposta assistant anterior da mesma
    sessão por ID, ignorando tool/system/reasoning; ausência não prova falha.
    context_chars é inteiro não negativo, limitado a 1200; texto atual é integral
    até o limite de admissão de 2 MiB, sempre sanitizado junto à proveniência.
    source_counts conta itens emitidos por fonte, não arquivos nem mensagens.
    """
    if isinstance(sources, (str, bytes)) or isinstance(session_ids, (str, bytes)):
        raise ValueError('selection_invalid')
    try:
        sources, session_ids = tuple(sources), tuple(session_ids)
    except TypeError:
        raise ValueError('selection_invalid') from None
    if (any(not isinstance(s, str) or s not in SOURCES for s in sources) or
            any(not isinstance(s, str) for s in session_ids) or
            delegation not in ('all', 'human', 'subagent') or
            type(context_chars) is not int or context_chars < 0):
        raise ValueError('selection_invalid')
    sources, session_ids = tuple(dict.fromkeys(sources)), tuple(dict.fromkeys(session_ids))
    context_chars = min(context_chars, 1200)
    home = Path(home).expanduser().absolute()
    coverage = {'messages_by_role': {}, 'excluded': {}, 'sources_read': [],
                'failures': [], 'status': 'ok', 'scope': 'selection',
                'source_counts': {source: 0 for source in sources}}
    blocked = False
    if sources:
        try:
            blocked = any(path.is_symlink() for path in (*reversed(home.parents), home))
            if blocked:
                _e._failure(coverage, 'home', 'symlink_rejected')
        except OSError:
            blocked = True
            _e._failure(coverage, 'home', 'home_read_error')
    items = []
    if not blocked:
        if {'tasks', 'feedback'} & set(sources):
            items.extend(_database(home, sources, session_ids, delegation, context_chars, coverage, snapshot))
        items.extend(_documents(home, sources, coverage, snapshot))
    kinds = {'task': 'tasks', 'feedback': 'feedback', 'skill': 'skills', 'memory': 'memories'}
    for item in items:
        coverage['source_counts'][kinds[item['kind']]] += 1
    return _e._sanitize({'items': items, 'coverage': coverage,
                         'selection': {'sources': list(sources), 'session_ids': list(session_ids),
                                       'delegation': delegation, 'context_chars': context_chars}})
