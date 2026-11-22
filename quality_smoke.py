"""Controles sintéticos pequenos pelo caminho real de classificação e HTML.

Não lê perfis. Não altera gabarito, não faz retry e não homologa produção.
"""
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path

from analysis import _private_file, _write
from study import canonical, digest


ROOT = Path(__file__).resolve().parent


def execute(args):
    import cli
    import quality
    if args.input or args.tenant or not args.work:
        raise ValueError('invalid_quality_input')
    source = ROOT / 'examples/quality-smoke.synthetic.json'
    expected = json.loads((ROOT / 'examples/quality-smoke.expected.json').read_text(encoding='utf-8'))
    sample = json.loads(source.read_text(encoding='utf-8'))
    contract = {'version': 1, 'sample_sha256': digest(sample), 'expected_sha256': digest(expected)}
    requested = Path(args.work).expanduser().absolute()
    if any(p.is_symlink() for p in (requested, *requested.parents)):
        raise ValueError('invalid_work')
    work = cli.private_work(args.work)
    manifest = work / 'smoke-manifest.json'
    if manifest.exists():
        _private_file(manifest)
        if json.loads(manifest.read_text(encoding='utf-8')) != contract:
            raise ValueError('campaign_mismatch')
    else:
        if os.path.lexists(work / 'quality'):
            raise ValueError('checkpoint_incomplete')
        _write(manifest, canonical(contract) + '\n')
    analyze = copy.copy(args)
    analyze.command, analyze.input, analyze.tenant = 'quality-analyze', str(source), 'synthetic-smoke'
    # Uma única resposta JSON da CLI; o relatório técnico permanece em disco.
    capture = io.StringIO()
    with redirect_stdout(capture):
        quality.execute(analyze, validation_controls=dict(contract, checks=expected['checks']))
    result = json.loads(capture.getvalue())['validation']
    print(canonical(result))
    return 0 if result['matched'] == result['total'] and not result['failed'] and not result['missing'] else 1


def restore_legacy_controls(work, input_sha256):
    """Recupera controles só se o contrato anterior ainda prova os hashes exatos."""
    path = work.parent / 'smoke-manifest.json'
    if not os.path.lexists(path):
        if os.path.lexists(work / 'smoke-result.json'):
            raise ValueError('checkpoint_incomplete')
        return None
    _private_file(path)
    frozen = json.loads(path.read_text(encoding='utf-8'))
    sample = json.loads((ROOT / 'examples/quality-smoke.synthetic.json').read_text(encoding='utf-8'))
    expected = json.loads((ROOT / 'examples/quality-smoke.expected.json').read_text(encoding='utf-8'))
    contract = {'version': 1, 'sample_sha256': digest(sample), 'expected_sha256': digest(expected)}
    if frozen != contract or contract['sample_sha256'] != input_sha256:
        raise ValueError('campaign_mismatch')
    return dict(contract, checks=expected['checks'])


def summarize(labels, controls, models):
    """Compara controles congelados; falha/ausência nunca conta como acerto."""
    index = {(label['event_id'], label['label_name']): label for label in labels}
    checks = []
    for control in controls['checks']:
        label = index.get((control['event_id'], control['label_name']))
        missing = label is None
        failed = label is not None and label['unknown_reason'] == 'classification_failed'
        observed = label['label_value'] if label else None
        checks.append(dict(case=control['event_id'], expected=control['expected'], observed=observed,
                           failed=failed, missing=missing,
                           matched=not missing and not failed and observed == control['expected']))
    return dict(version=1, total=len(checks), matched=sum(c['matched'] for c in checks),
                failed=sum(c['failed'] for c in checks), missing=sum(c['missing'] for c in checks),
                qualification='exploratory_synthetic_controls', models=models,
                controls_sha256=controls['expected_sha256'], input_sha256=controls['sample_sha256'], checks=checks)
