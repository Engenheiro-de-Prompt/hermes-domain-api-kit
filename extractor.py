"""Extração local portátil de fontes Hermes (somente biblioteca padrão).

Falhas são códigos estáveis em coverage, nunca mensagens SQLite com dados.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing


WRAPPERS = ('[CONTEXT COMPACTION', '[ASYNC', '[Your active',
            '[IMPORTANT:', '[INTERNAL NOTIFICATION')


def discover_home(explicit=None):
    """Descobre uma única raiz, sem explorar perfis adicionais."""
    return Path(explicit if explicit is not None else
                os.environ.get('HERMES_HOME') or Path.home() / '.hermes').expanduser()


MAX_CONTEXT_CHARS = 512


def _redact(text):
    """Defesa por formatos conhecidos, não um detector universal de segredos."""
    text = re.sub(r'(?i)\bBearer\s+(?!\[REDACTED\])[^\s\"\'<>;,)}\]]+',
                  'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)(\b(?:[a-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|'
                  r'auth[_-]?token|secret[_-]?key|secret[_-]?access[_-]?key|password)'
                  r'\b[\"\']?\s*[:=]\s*)(?:\"[^\"\r\n]*\"|\'[^\'\r\n]*\'|[^\s,;}]+)',
                  r'\1[REDACTED]', text)
    return re.sub(r'\b(?:lr_(?:live|client|agent)_[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9]{8,}|'
                  r'gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|'
                  r'AIza[A-Za-z0-9_-]{8,}|AKIA[A-Z0-9]{16}|'
                  r'xox[baprs]-[A-Za-z0-9-]{8,})\b', '[REDACTED]', text)


def _sanitize(value):
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, list):
        return [_sanitize(part) for part in value]
    if isinstance(value, dict):
        return {_sanitize(key): _sanitize(part) for key, part in value.items()}
    return value


def _context(text):
    return _redact(text)[:MAX_CONTEXT_CHARS] if isinstance(text, str) else ''


def _hash(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def _count(mapping, key):
    mapping[key] = mapping.get(key, 0) + 1


def _failure(coverage, path, code):
    coverage['failures'].append({'path': path, 'code': code})
    coverage['status'] = 'error'


def _database(home, coverage):
    path = home / 'state.db'
    if not _allowed_path(home, path, coverage):
        return []
    for suffix in ('-wal', '-shm', '-journal'):
        if not _allowed_path(home, home / ('state.db' + suffix), coverage):
            return []
    if not path.is_file():
        _failure(coverage, 'state.db', 'database_missing')
        return []
    items = []
    seen = {}
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            cols = {table: {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
                    for table in ('sessions', 'messages')}
            if not {'id'} <= cols['sessions'] or not {'id', 'session_id', 'role', 'content'} <= cols['messages']:
                _failure(coverage, 'state.db', 'schema_required')
                return []
            source = 'source' if 'source' in cols['sessions'] else 'NULL'
            title = 'title' if 'title' in cols['sessions'] else 'NULL'
            timestamp = 'timestamp' if 'timestamp' in cols['messages'] else 'NULL'
            sessions = {row[0]: row[1:] for row in db.execute(
                'SELECT id, ' + source + ', ' + title + ' FROM sessions')}
            for mid, sid, role, text, stamp, size in db.execute(
                    'SELECT id, session_id, role, CASE WHEN role=\'user\' AND '
                    'length(CAST(content AS BLOB)) <= ? THEN content ELSE NULL END, ' +
                    timestamp + ', length(CAST(content AS BLOB)) FROM messages ORDER BY id',
                    (MAX_FILE_BYTES,)):
                role_label = role if role in ('user', 'assistant', 'tool', 'system') else 'other'
                _count(coverage['messages_by_role'], role_label)
                if role != 'user':
                    _count(coverage['excluded'], 'non_user')
                    continue
                if size is not None and size > MAX_FILE_BYTES:
                    _failure(coverage, 'state.db', 'message_too_large')
                    _count(coverage['excluded'], 'message_too_large')
                    continue
                if not isinstance(text, str) or not text.strip():
                    _count(coverage['excluded'], 'empty_or_nontext')
                    continue
                if text.lstrip().startswith(WRAPPERS):
                    _count(coverage['excluded'], 'automatic_wrapper')
                    continue
                source_value, title_value = sessions.get(sid, ('', ''))
                # Sem timestamp não existe evidência de cópia: preservar cada evento.
                event = stamp if stamp is not None else ('message', mid)
                identity = _hash('task', sid, role, event, _hash(text))
                ref = {'path': 'state.db', 'session_id': sid,
                       'message_id': mid, 'timestamp': stamp}
                if identity in seen:
                    seen[identity]['provenance'].append(ref)
                    _count(coverage['excluded'], 'duplicate')
                    continue
                item = {'id': identity, 'kind': 'task', 'text': text,
                        'context': _context(title_value), 'delegated': source_value == 'subagent',
                        'provenance': [ref]}
                seen[identity] = item
                items.append(item)
    except (sqlite3.Error, OSError, ValueError):
        _failure(coverage, 'state.db', 'database_read_error')
        return []
    coverage['sources_read'].append('state.db')
    return items


def _sections(text):
    """Seções Markdown ou separadores §; preserva cabeçalhos no texto."""
    return [part.strip() for part in re.split(r'(?m)(?=^#{1,6}\s)|§', text) if part.strip()]


MAX_FILE_BYTES = 2 * 1024 * 1024


def _allowed_path(home, path, coverage):
    relative = path.relative_to(home)
    current = home
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _failure(coverage, relative.as_posix(), 'symlink_rejected')
            return False
    return True


def _sensitive(path):
    return any(re.search(r'(?i)^(?:\.env(?:\.|$)|auth(?:entication)?(?:[._-]|$)|credentials?(?:[._-]|$)|'
                         r'config(?:[._-]|$)|system(?:[ _-]?prompts?)?(?:[._-]|$)|'
                         r'(?:soul|agents|prompts|thinking|chain[ _-]of[ _-]thought)(?:[._-]|$)|'
                         r'reasoning(?:[._-]|$)|racioc[ií]nio(?:[._-]|$)|profiles$)', part)
               for part in path.parts)


def _read_document(path, relative, coverage):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            _failure(coverage, relative, 'file_too_large')
            return None
        with path.open('rb') as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            _failure(coverage, relative, 'file_too_large')
            return None
        return raw.decode('utf-8')
    except UnicodeError:
        _failure(coverage, relative, 'invalid_utf8')
    except OSError:
        _failure(coverage, relative, 'file_read_error')
    return None


def _documents(home, coverage):
    candidates = []
    skills = home / 'skills'
    if _allowed_path(home, skills, coverage) and skills.is_dir():
        def walk_error(_error):
            _failure(coverage, 'skills', 'directory_read_error')
        for base, dirs, files in os.walk(skills, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(name for name in dirs
                             if not _sensitive(Path(name)) and
                             _allowed_path(home, Path(base) / name, coverage))
            for name in sorted(files):
                path = Path(base) / name
                relative = path.relative_to(skills)
                if _sensitive(relative):
                    _count(coverage['excluded'], 'sensitive_path')
                    continue
                if not _allowed_path(home, path, coverage):
                    continue
                if path.is_file() and (path.suffix.lower() == '.md' or
                        (path.suffix.lower() in {'.txt', '.yaml', '.json', '.py'} and
                         {'references', 'templates'} & set(relative.parts[:-1]))):
                    candidates.append((path, 'skill'))
    for relative in ('memories/MEMORY.md', 'memories/USER.md', 'MEMORY.md', 'USER.md'):
        path = home / relative
        if _allowed_path(home, path, coverage) and path.is_file():
            candidates.append((path, 'memory'))
    items = []
    for path, kind in candidates:
        relative = path.relative_to(home).as_posix()
        text = _read_document(path, relative, coverage)
        if text is None:
            continue
        coverage['sources_read'].append(relative)
        sections = _sections(text) if kind == 'memory' else [text]
        for index, section in enumerate(sections):
            if not section.strip():
                continue
            items.append({'id': _hash(kind, relative, index, section), 'kind': kind,
                          'text': section, 'context': _context(relative), 'delegated': False,
                          'provenance': [{'path': relative, 'section': index}]})
    return items


def extract(home):
    """Lê fontes autorizadas e retorna itens + cobertura, inclusive erros explícitos."""
    home = Path(home).expanduser().resolve()
    coverage = {'messages_by_role': {}, 'excluded': {}, 'sources_read': [],
                'failures': [], 'status': 'ok'}
    items = _database(home, coverage)
    items.extend(_documents(home, coverage))
    return _sanitize({'items': items, 'coverage': coverage})
