"""Downloader-only network access; atomic files verified against pinned manifests."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path

from packages.ir import safe_path


@contextmanager
def cache_lock(root):
    import fcntl
    root = Path(root)
    if root.is_symlink():
        raise ValueError('PARSER_MODEL_PATH')
    root.mkdir(parents=True, exist_ok=True)
    path = safe_path(root, 'prepare.lock', must_exist=False)
    with path.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def valid(path, spec):
    if not path.is_file() or path.stat().st_size != spec['size']:
        return False
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest() == spec['sha256']


def download(specs, root, client, progress=lambda **fields: None):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('PARSER_MODEL_PATH')
    root.mkdir(parents=True, exist_ok=True)
    # Reject the entire manifest before starting any network or file writes.
    for spec in specs:
        safe_path(root, spec['path'], must_exist=False)
    total, completed = sum(s['size'] for s in specs), 0
    for spec in specs:
        target = safe_path(root, spec['path'], must_exist=False)
        if valid(target, spec):
            completed += spec['size']
            progress(downloaded_bytes=completed, total_bytes=total)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = safe_path(root, spec['path'] + '.part', must_exist=False)
        count, sha = 0, hashlib.sha256()
        try:
            with client.stream('GET', spec['url'], follow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open('wb') as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        count += len(chunk)
                        if count > spec['size']:
                            raise ValueError('PARSER_MODEL_HASH_MISMATCH')
                        sha.update(chunk)
                        handle.write(chunk)
                        progress(downloaded_bytes=completed + count, total_bytes=total)
                    handle.flush()
                    os.fsync(handle.fileno())
            if count != spec['size'] or sha.hexdigest() != spec['sha256']:
                raise ValueError('PARSER_MODEL_HASH_MISMATCH')
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        completed += count
