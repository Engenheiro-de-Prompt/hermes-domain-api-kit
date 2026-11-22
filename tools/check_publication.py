"""Fail-closed publication gate. Prints locations/rules, never matching content."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    'private_key': re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    'token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{28,}|lr_(?:client|agent)[_-][A-Za-z0-9_-]{24,})\b'),
    'donor_path': re.compile(r'/home/(?:virtualis)(?:/|\b)|/mnt/(?:novo-volume)(?:/|\b)|/run/user/[0-9]+/credentials/|hermes-isolated[0-9]*-workspace'),
}
PRIVATE_BASENAMES = {'corpus.json', 'snapshot.json', 'manifest.json', 'pipeline.json', 'labels.json', 'report.json', 'narrative.json', 'privacy.json', 'dashboard.html', 'feedback.html', 'smoke-manifest.json', 'smoke-result.json'}
BAD_SUFFIXES = ('.jsonl', '.csv', '.db', '.sqlite', '.sqlite3', '.zip', '.log', '.key', '.pem', '.wav', '.mp3', '.mp4')


def inspect(path, content):
    issues = []
    p = Path(path)
    if p.name in PRIVATE_BASENAMES or p.name.startswith('.env') or str(p).startswith(('private/', 'work/', 'outputs/', 'runs/', 'analysis/')) or p.name.endswith(BAD_SUFFIXES):
        issues.append((0, 'private_artifact_name'))
    try:
        if b'\x00' in content:
            raise UnicodeError()
        text = content.decode('utf-8')
    except UnicodeError:
        issues.append((0, 'unexpected_binary'))
        return issues
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in RULES.items():
            if pattern.search(line):
                issues.append((number, name))
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Audit bytes actually staged for commit')
    args = parser.parse_args(argv)
    command = ['git', 'ls-files', '-z'] if args.staged else ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard']
    paths = sorted(set(subprocess.check_output(command, cwd=ROOT).decode().split('\0')) - {''})
    problems = []
    modes = {}
    if args.staged:
        for entry in subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).decode().split('\0'):
            if entry:
                metadata, path = entry.split('\t', 1)
                modes[path] = metadata.split()[0]
    for path in paths:
        disk = ROOT / path
        if args.staged and modes.get(path) not in ('100644', '100755'):
            problems.append((path, 0, 'symlink_or_unsupported_git_mode'))
            continue
        if args.staged:
            raw = subprocess.check_output(['git', 'show', ':' + path], cwd=ROOT)
        elif disk.is_symlink():
            problems.append((path, 0, 'symlink'))
            continue
        elif not disk.is_file():
            continue
        else:
            raw = disk.read_bytes()
        problems.extend((path, line, rule) for line, rule in inspect(path, raw))
    for path, line, rule in problems:
        print(f'{path}:{line}: {rule}')
    print(f'publication_gate files={len(paths)} issues={len(problems)} mode={"index" if args.staged else "worktree"}')
    return int(bool(problems))


if __name__ == '__main__':
    sys.exit(main())
