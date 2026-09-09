"""Provider configuration lives outside content/DB backups, never in a DB receipt.

Each committed revision is immutable; a fsynced atomic pointer is the commit.
Readers resolve profile and credential from that same revision, not two globals.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import copy
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from packages.domain.errors import DomainError, require

DEFAULT_ENDPOINT = 'https://api.openai.com/v1/responses'
REVISION = re.compile(r'[a-f0-9]{32}')


def config_root():
    return Path(os.environ.get('PROVIDER_CONFIG_DIR', '/provider_config'))


def validate_endpoint(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('PROVIDER_ENDPOINT')
    try:
        url = urlsplit(value)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment or '?' in value or '#' in value
                or '\\' in value or not url.path or url.path == '/' or url.port == 0):
            raise ValueError('PROVIDER_ENDPOINT')
        _ = url.port
    except (ValueError, UnicodeError):
        raise ValueError('PROVIDER_ENDPOINT') from None
    return value


def _read(path, limit=32768):
    from packages.ir import strict_loads
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    return strict_loads(path.read_bytes())


def _revision(root, identifier):
    if not isinstance(identifier, str) or not REVISION.fullmatch(identifier):
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    path = root / 'versions' / identifier
    if path.is_symlink() or (root / 'versions').is_symlink():
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    return path


def _current(root):
    pointer = root / 'current.json'
    if root.is_symlink():
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    if not pointer.exists() and not pointer.is_symlink():
        return None
    value = _read(pointer)
    if (set(value) != {'revision', 'generation'} or type(value['generation']) is not int or value['generation'] < 1):
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    _revision(root, value['revision'])
    return value


def _bundle(root, identifier):
    from packages.domain.config import validate_public_profile
    path = _revision(root, identifier)
    profile = validate_public_profile(_read(path / 'profile.json'), allow_incomplete=True)
    if profile.get('config_revision') != identifier:
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    return profile


def managed_profile():
    root = config_root()
    pointer = _current(root)
    return _bundle(root, pointer['revision']) if pointer else None


def _key_present(path):
    if path.is_symlink():
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    return path.is_file() and 0 < path.stat().st_size <= 8192


def _availability(profile, present):
    from packages.domain.config import missing_profile_fields
    missing = missing_profile_fields({**profile, **_display_defaults(profile)})
    if profile.get('auth_mode', 'bearer') != 'none' and not present:
        missing.append('api_key')
    return {'missing_fields': missing, 'dispatch_configuration_ready': bool(profile.get('configured')) and not missing}


def _display_defaults(profile):
    """View-only defaults never alter an immutable legacy profile or its hash."""
    from packages.domain.config import DEFAULT_PROVIDER_LIMITS
    return {**{key: profile.get(key, default) for key, default in DEFAULT_PROVIDER_LIMITS.items()},
            'token_limits_defaults': dict(DEFAULT_PROVIDER_LIMITS),
            'cost_control_enabled': profile.get('cost_control_enabled', bool(profile.get('configured')))}


def configuration_view():
    from packages.domain.config import external_provider_profile, missing_profile_fields
    from packages.ir import digest
    from .registry import protocol_definition
    root = config_root()
    pointer = _current(root)
    if pointer:
        profile = _bundle(root, pointer['revision'])
        present = _key_present(_revision(root, pointer['revision']) / 'key')
        return {**profile, 'profile_hash': digest(profile), 'generation': pointer['generation'],
                'has_api_key': present, 'credential_status': 'stored' if present else 'missing', 'config_source': 'managed',
                **_availability(profile, present), **_display_defaults(profile)}
    profile = external_provider_profile()
    definition = protocol_definition(profile.get('api_protocol', 'responses'))
    # The legacy secret is normally mounted only in the worker, so the API
    # cannot infer absence from an inaccessible path or read it to check it.
    return {**profile, 'endpoint': profile.get('endpoint', definition['endpoint']),
            'api_protocol': profile.get('api_protocol', 'responses'), 'auth_mode': profile.get('auth_mode', definition['auth_mode']), 'profile_hash': digest(profile),
            'generation': 0, 'has_api_key': None if profile.get('configured') else False,
            'credential_status': 'external_unverified' if profile.get('configured') else 'missing',
            'config_source': 'external' if profile.get('configured') else 'unconfigured',
            'missing_fields': [] if profile.get('configured') else missing_profile_fields({**profile, **_display_defaults(profile)}),
            'dispatch_configuration_ready': False, **_display_defaults(profile)}


def _fsync_dir(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@contextmanager
def _locked(root):
    if root.is_symlink():
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    lockpath = root / '.lock'
    if lockpath.is_symlink():
        raise ValueError('PROVIDER_CONFIG_STORAGE')
    with lockpath.open('a+b') as handle:
        os.chmod(lockpath, 0o600)
        if os.name == 'nt':
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def save_configuration(profile, api_key, clear_api_key, expected_etag, idempotency_key):
    """CAS and secret-aware idempotency; only keyed HMACs are journaled."""
    from packages.domain.config import validate_public_profile, external_provider_profile, DEFAULT_PROVIDER_LIMITS
    from packages.ir import digest
    from .registry import CLAUDE_API_VERSION, protocol_definition
    require(expected_etag is not None, 'PRECONDITION_REQUIRED', status=428)
    require(isinstance(idempotency_key, str) and 1 <= len(idempotency_key) <= 128 and idempotency_key.isascii(),
            'IDEMPOTENCY_REQUIRED', status=428)
    require(isinstance(profile, dict) and not {'config_revision', 'credential_revision'} & profile.keys(), 'PROVIDER_PUBLIC_FIELDS', status=422)
    require('cost_control_enabled' not in profile or type(profile['cost_control_enabled']) is bool,
            'PROVIDER_CONFIG_INVALID', status=422)
    profile = copy.deepcopy(profile)
    # Null means not supplied; preserve explicit numeric zero, never invent a price.
    profile = {key: value for key, value in profile.items() if value is not None}
    profile.setdefault('configured', True)
    profile.setdefault('api_protocol', 'responses')
    try:
        definition = protocol_definition(profile['api_protocol'])
    except ValueError:
        raise DomainError('PROVIDER_CONFIG_INVALID', status=422) from None
    profile.setdefault('provider', definition['provider'])
    profile.setdefault('auth_mode', definition['auth_mode'])
    profile.setdefault('enabled_pairs', [])
    if profile['api_protocol'] == 'claude_messages':
        if profile.get('api_version') in (None, ''):
            profile['api_version'] = CLAUDE_API_VERSION
    profile.setdefault('price', {})
    if isinstance(profile['price'], dict):
        profile['price'] = {key: value for key, value in profile['price'].items() if value is not None}
    profile.setdefault('prompt_version', 'translation-v1')
    profile.setdefault('privacy_revision', 'provider-settings-v1')
    if isinstance(profile.get('price'), dict):
        profile['price'].setdefault('revision', 'price-' + digest(profile['price'])[:24])
    profile.setdefault('profile_revision', 'settings-' + digest(profile)[:24])
    try:
        profile = validate_public_profile(profile, allow_incomplete=True)
    except (ValueError, TypeError, KeyError):
        raise DomainError('PROVIDER_CONFIG_INVALID', status=422) from None
    require(type(clear_api_key) is bool and (api_key is None or isinstance(api_key, str)), 'REQUEST_INVALID', status=422)
    key = (api_key or '').strip()
    require(len(key) <= 8192 and all(33 <= ord(c) < 127 for c in key), 'PROVIDER_KEY_INVALID', status=422)
    require(not (key and clear_api_key), 'PROVIDER_KEY_ACTION_CONFLICT', status=422)
    root = config_root()
    with _locked(root):
        pointer = _current(root)
        saltpath = root / '.receipt-hmac-key'
        if not saltpath.exists():
            _write(saltpath, os.urandom(32))
        if saltpath.is_symlink() or saltpath.stat().st_size != 32:
            raise ValueError('PROVIDER_CONFIG_STORAGE')
        body_hash = hmac.new(saltpath.read_bytes(), _json({'profile': profile, 'api_key': key, 'clear_api_key': clear_api_key}), hashlib.sha256).hexdigest()
        token = hashlib.sha256(idempotency_key.encode('ascii')).hexdigest()
        cursor = pointer['revision'] if pointer else None
        visited = set()
        while cursor is not None:
            if cursor in visited:
                raise ValueError('PROVIDER_CONFIG_STORAGE')
            visited.add(cursor)
            operation = _read(_revision(root, cursor) / 'operation.json')
            if operation['idempotency_hash'] == token:
                require(operation['body_hmac'] == body_hash, 'IDEMPOTENCY_CONFLICT')
                old_profile = _bundle(root, cursor)
                present = _key_present(_revision(root, cursor) / 'key')
                return {**old_profile, 'profile_hash': digest(old_profile), 'generation': operation['generation'],
                        'has_api_key': present, 'credential_status': 'stored' if present else 'missing', 'config_source': 'managed',
                        **_availability(old_profile, present), **_display_defaults(old_profile)}
            cursor = operation['previous_revision']
        generation = pointer['generation'] if pointer else 0
        require(expected_etag == f'"{generation}"', 'PRECONDITION_FAILED', status=412)
        old = _bundle(root, pointer['revision']) if pointer else external_provider_profile()
        # Effective defaults depend on the current revision only after the
        # idempotency lookup. Replaying an earlier omitted-flag request must
        # return its original revision even if another client toggled later.
        profile.setdefault('cost_control_enabled', old.get('cost_control_enabled', bool(old.get('configured'))))
        for name, default in DEFAULT_PROVIDER_LIMITS.items():
            profile.setdefault(name, old.get(name, default))
        profile = validate_public_profile(profile, allow_incomplete=True)
        old_key_path = (_revision(root, pointer['revision']) / 'key') if pointer else Path(os.environ.get('PROVIDER_KEY_FILE', '/run/secrets/provider_key'))
        if not clear_api_key and not key and (pointer or old.get('configured')):
            present = _key_present(old_key_path)
            if pointer is None and old.get('auth_mode', 'bearer') != 'none':
                require(_key_present(old_key_path), 'PROVIDER_KEY_REQUIRED')
            if present:
                require((old.get('endpoint', '' if pointer else DEFAULT_ENDPOINT), old.get('api_protocol', 'responses'), old.get('auth_mode', 'bearer')) ==
                        (profile.get('endpoint', ''), profile['api_protocol'], profile['auth_mode']), 'PROVIDER_KEY_REBIND_REQUIRED')
                key = old_key_path.read_text('utf-8').strip()
                require(len(key) <= 8192 and all(33 <= ord(c) < 127 for c in key), 'PROVIDER_KEY_INVALID', status=422)
        identifier = uuid.uuid4().hex
        credential = old.get('credential_revision') if not clear_api_key and not (api_key or '').strip() and pointer else uuid.uuid4().hex
        new_profile = {**profile, 'config_revision': identifier, 'credential_revision': credential}
        versions = root / 'versions'
        if versions.is_symlink():
            raise ValueError('PROVIDER_CONFIG_STORAGE')
        versions.mkdir(exist_ok=True, mode=0o700)
        directory = _revision(root, identifier)
        directory.mkdir(mode=0o700)
        _write(directory / 'profile.json', _json(new_profile))
        if key and not clear_api_key:
            _write(directory / 'key', key.encode())
        operation = {'idempotency_hash': token, 'body_hmac': body_hash, 'generation': generation + 1,
                     'previous_revision': pointer['revision'] if pointer else None}
        _write(directory / 'operation.json', _json(operation))
        _fsync_dir(directory); _fsync_dir(versions)
        temporary = root / ('.current-' + identifier)
        _write(temporary, _json({'revision': identifier, 'generation': generation + 1}))
        os.replace(temporary, root / 'current.json')
        _fsync_dir(root)
        present = bool(key and not clear_api_key)
        return {**new_profile, 'profile_hash': digest(new_profile), 'generation': generation + 1,
                'has_api_key': present, 'credential_status': 'stored' if present else 'missing', 'config_source': 'managed',
                **_availability(new_profile, present), **_display_defaults(new_profile)}


def resolve_provider_credentials(frozen_profile):
    """Worker only: exact revision credentials, never another endpoint's key."""
    from packages.domain.config import external_provider_profile
    from packages.providers.contract import ProviderFailure
    from .registry import validate_protocol_profile
    try:
        identifier = frozen_profile.get('config_revision')
        if identifier:
            bound = _bundle(config_root(), identifier)
            if not bound.get('configured'):
                raise ValueError('PROVIDER_CONFIG_INCOMPLETE')
            if any(frozen_profile.get(key) != value for key, value in bound.items()):
                raise ValueError('PROVIDER_PROFILE_STALE')
            path = _revision(config_root(), identifier) / 'key'
        else:
            if _current(config_root()) is not None:
                raise ValueError('PROVIDER_PROFILE_STALE')
            bound = external_provider_profile()
            if not bound.get('configured') or any(frozen_profile.get(key) != value for key, value in bound.items()):
                raise ValueError('PROVIDER_PROFILE_STALE')
            path = Path(os.environ.get('PROVIDER_KEY_FILE', '/run/secrets/provider_key'))
        definition = validate_protocol_profile(bound)
        auth_mode = bound.get('auth_mode', definition['auth_mode'])
        if auth_mode == 'none':
            path = None
        elif not _key_present(path):
            raise ValueError('PROVIDER_KEY_REQUIRED')
        return validate_endpoint(bound.get('endpoint', definition['endpoint'])), bound.get('api_protocol', 'responses'), auth_mode, path
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ProviderFailure('PROVIDER_CONFIG', 'not_sent') from None
