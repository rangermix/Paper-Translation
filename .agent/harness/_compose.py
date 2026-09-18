"""Per-run test inputs layered over the single checked-in Compose template."""
if __package__:
    from ._project import ROOT
else:
    from _project import ROOT
import json
from pathlib import Path


def write_offline_override(directory):
    """Create fresh offline mounts without overwriting an earlier run's input."""
    directory = Path(directory).resolve()
    mounts = [
        {'type': 'bind', 'source': (ROOT / '.agent/harness').as_posix(), 'target': '/harness', 'read_only': True},
        {'type': 'bind', 'source': directory.as_posix(), 'target': '/evidence'},
    ]
    config = {'services': {
        'db': {'image': '${DATABASE_IMAGE:-bilingual-personal-pdf-db:acceptance-candidate}'},
        'app': {'volumes': mounts}, 'maintenance': {'volumes': mounts},
    }, 'networks': {name: {'internal': True} for name in ('backend', 'http', 'provider_egress')}}
    path = directory / 'offline-compose.json'
    with path.open('x', encoding='utf-8') as handle:
        json.dump(config, handle, indent=2)
        handle.write('\n')
    return path


def provider_override(profile, *, key=None):
    """Explicit approved/fixture input only; never reads a profile or key file.

    Live callers must validate their existing authorization before constructing
    this override. Offline callers may supply their synthetic public profile
    alone to exercise unavailable-credential handling.
    """
    services = {name: {
        'environment': {'PROVIDER_PROFILE_FILE': '/config/provider-profile.json'},
        'volumes': [{'type': 'bind', 'source': Path(profile).resolve().as_posix(),
                     'target': '/config/provider-profile.json', 'read_only': True}],
    } for name in ('app', 'worker')}
    result = {'services': services}
    if key is not None:
        services['worker']['environment']['PROVIDER_KEY_FILE'] = '/run/secrets/provider_key'
        services['worker']['secrets'] = ['provider_key']
        result['secrets'] = {'provider_key': {'file': Path(key).resolve().as_posix()}}
    return result
