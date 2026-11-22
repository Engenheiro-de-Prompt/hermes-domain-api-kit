"""Gera no repositório apenas o HTML da fixture pública sintética.

Para dados reais, use cli.py quality-report/quality-analyze com --work externo.
Nenhuma credencial, perfil, banco ou endpoint é acessado por este exemplo.
"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    """Exercita a CLI de produção e copia somente o HTML agregado sintético."""
    import cli
    from analysis import _write
    with tempfile.TemporaryDirectory(prefix='hermes-quality-public-demo-') as directory:
        work = Path(directory) / 'work'
        with redirect_stdout(io.StringIO()):
            result = cli.main(['quality-report', '--input', str(ROOT / 'examples/quality-events.synthetic.json'),
                               '--tenant', 'synthetic', '--work', str(work)])
        if result:
            return result
        target = ROOT / 'examples/quality-dashboard.synthetic.html'
        _write(target, (work / 'quality/dashboard.html').read_text(encoding='utf-8'))
        print(str(target))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
