"""Pinned parser artifacts. Importing or listing this catalogue never downloads."""
from functools import lru_cache

from packages.ir import digest, strict_loads
from packages.paths import ROOT
from .profiles import PARSER_PROFILES, selected_profile

VLM_LOCK_PATH = ROOT / 'deployment/parser-vlm-models.lock.json'


@lru_cache
def vlm_lock():
    return strict_loads(VLM_LOCK_PATH.read_bytes())


def vlm_model(profile):
    selected_profile({'parser_profile_revision': profile})
    return next(m for m in vlm_lock()['models'] if m['id'] == profile)


def download_spec(profile):
    """Flatten the selected pinned full-page model into cache-relative files."""
    model = vlm_model(profile)
    prefix = model['repo'].replace('/', '--') + '/' + model['revision']
    return [{'path': prefix + '/' + f['path'], 'size': f['size'], 'sha256': f['sha256'],
             'url': f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{f['path']}"}
            for f in model['files']]


def manifest_id(profile):
    return digest(download_spec(profile))


def public_models():
    result = []
    for row in PARSER_PROFILES:
        spec = download_spec(row['id'])
        model = vlm_model(row['id'])
        result.append({**row, 'download_bytes': sum(f['size'] for f in spec),
                       'revision': model.get('revision'), 'license': model.get('license'),
                       'manifest_id': digest(spec)})
    return result
