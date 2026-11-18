"""Create a minimal, private ZIP containing only result artifacts."""
import os
from pathlib import Path
import stat
import tempfile
import zipfile

from study import LABELS


def package_results(result_dir, archive_path):
    raw_result_dir=Path(result_dir).expanduser()
    raw_archive_path=Path(archive_path).expanduser()
    if raw_result_dir.is_symlink() or raw_archive_path.is_symlink():
        raise ValueError('invalid_result_directory')
    result_dir=raw_result_dir.resolve(strict=True)
    archive_path=raw_archive_path.resolve()
    if not result_dir.is_dir():
        raise ValueError('invalid_result_directory')
    names=['summary.json','dataset.csv']+[f'datasets/{label}.jsonl' for label in LABELS]
    sources=[]
    for name in names:
        source=result_dir/name
        if source.is_symlink() or not source.is_file():
            raise ValueError('incomplete_result_artifacts')
        if result_dir not in source.resolve().parents:
            raise ValueError('invalid_result_artifacts')
        sources.append((source,name))
    archive_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(archive_path.parent,0o700)
    descriptor,temporary_name=tempfile.mkstemp(prefix=archive_path.name+'.',suffix='.tmp',dir=archive_path.parent)
    temporary=Path(temporary_name)
    try:
        with os.fdopen(descriptor,'w+b') as file:
            with zipfile.ZipFile(file,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
                for source,name in sources:
                    info=zipfile.ZipInfo(name)
                    info.compress_type=zipfile.ZIP_DEFLATED
                    info.external_attr=(stat.S_IFREG|0o600)<<16
                    bundle.writestr(info,source.read_bytes())
            file.flush()
            os.fsync(file.fileno())
            with zipfile.ZipFile(file,'r') as bundle:
                if bundle.testzip() is not None:
                    raise zipfile.BadZipFile('invalid_result_archive_crc')
        os.replace(temporary,archive_path)
        os.chmod(archive_path,0o600)
        return archive_path
    finally:
        if temporary.exists():
            temporary.unlink()
