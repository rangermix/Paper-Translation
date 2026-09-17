"""Bounded, resumable-by-file downloads; verified files become Docker OCI layers."""
import hashlib
import io
import os
from pathlib import Path
import tarfile

from .catalog import artifact, sha


def file_path(root, name):
    if not name or Path(name).name != name or name in ('.', '..') or '\\' in name:
        raise ValueError('LOCAL_MODEL_PATH')
    path = root / name
    if root.is_symlink() or path.is_symlink():
        raise ValueError('LOCAL_MODEL_PATH')
    return path


def valid(path, spec):
    if not path.is_file() or path.stat().st_size != spec['size']:
        return False
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest() == spec['sha256']


def download(model, root, client, progress=lambda **kw: None):
    root = Path(root)
    for spec in model['files']:
        file_path(root, spec['path'])
    root.mkdir(parents=True, exist_ok=True)
    completed = 0
    total = sum(f['size'] for f in model['files'])
    for spec in model['files']:
        target = file_path(root, spec['path'])
        if valid(target, spec):
            completed += spec['size']
            progress(downloaded_bytes=completed, total_bytes=total)
            continue
        temporary = file_path(root, spec['path'] + '.part')
        digest = hashlib.sha256()
        size = 0
        try:
            url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{spec['path']}"
            with client.stream('GET', url, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open('wb') as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > spec['size']:
                            raise ValueError('LOCAL_MODEL_HASH')
                        digest.update(chunk); handle.write(chunk)
                        progress(downloaded_bytes=completed + size, total_bytes=total)
                    handle.flush(); os.fsync(handle.fileno())
            if size != spec['size'] or digest.hexdigest() != spec['sha256']:
                raise ValueError('LOCAL_MODEL_HASH')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        completed += size


def archive(model, root):
    """Stream DMR's tar format without a second multi-GB archive on disk."""
    package = artifact(model)
    entries = [('blobs/sha256/' + f['sha256'], file_path(root, f['path']), f['size']) for f in model['files']]
    entries += [('blobs/sha256/' + sha(package['config']), package['config'], len(package['config'])),
                ('manifest.json', package['manifest'], len(package['manifest']))]
    for name, source, size in entries:
        info = tarfile.TarInfo(name); info.size = size; info.mode = 0o644
        yield info.tobuf(format=tarfile.USTAR_FORMAT)
        with (source.open('rb') if isinstance(source, Path) else io.BytesIO(source)) as handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk
        yield b'\0' * (-size % 512)
    yield b'\0' * 1024
