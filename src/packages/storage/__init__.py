"""Generated storage keys and immutable, fsync-before-rename writes."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import uuid

from packages.domain.errors import require


def safe_path(root, key, *, must_exist=False):
    root = Path(root).resolve()
    require(isinstance(key, str) and '\\' not in key and ':' not in key and '\x00' not in key, 'UNSAFE_PATH', status=400)
    parts = PurePosixPath(key)
    require(not parts.is_absolute() and all(p not in ('', '.', '..') for p in key.split('/')), 'UNSAFE_PATH', status=400)
    candidate = root.joinpath(*parts.parts)
    for ancestor in (candidate, *candidate.parents):
        if ancestor == root:
            break
        require(not ancestor.is_symlink(), 'UNSAFE_PATH', status=400)
    require(candidate.resolve().is_relative_to(root), 'UNSAFE_PATH', status=400)
    if must_exist:
        require(candidate.is_file(), 'ASSET_MISSING', status=409)
    return candidate


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(root, key, data, *, immutable=True):
    path = safe_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        require(path.read_bytes() == data, 'IMMUTABLE_CONFLICT')
        return path
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(temporary, path)
            except FileExistsError:
                require(path.read_bytes() == data, 'IMMUTABLE_CONFLICT')
            temporary.unlink()
        else:
            os.replace(temporary, path)
        if os.name != 'nt':
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def write_snapshot(root, key, value):
    from packages.ir import canonical_bytes
    data = canonical_bytes(value)
    atomic_write(root, key, data)
    return hashlib.sha256(data).hexdigest()


def read_snapshot(root, entity):
    from packages.ir import strict_loads
    path = safe_path(root, entity.storage_key, must_exist=True)
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == entity.snapshot_hash, 'SNAPSHOT_CORRUPT')
    return strict_loads(data)
