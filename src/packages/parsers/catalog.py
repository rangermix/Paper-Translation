"""Pinned parser artifacts. Importing or listing this catalogue never downloads."""
from functools import lru_cache

from packages.ir import digest, strict_loads
from packages.paths import ROOT
from .profiles import (DOCLING_PROFILE, GRANITE_MODEL, GRANITE_PROFILE, PADDLE_MODEL,
                       PADDLE_PROFILE, PARSER_PROFILES, VLM_PROFILES, selected_profile)

VLM_LOCK_PATH = ROOT / 'deployment/parser-vlm-models.lock.json'


@lru_cache
def vlm_lock():
    return strict_loads(VLM_LOCK_PATH.read_bytes())


def vlm_model(profile):
    selected_profile({'parser_profile_revision': profile})
    return next(m for m in vlm_lock()['models'] if m['id'] == profile)


def repositories(profile, lock):
    """Only the selected pipeline's dependencies are required in its cache."""
    selected_profile({'parser_profile_revision': profile})
    ids = ({GRANITE_MODEL} if profile == GRANITE_PROFILE else
           {PADDLE_MODEL, 'PaddlePaddle/PP-DocLayoutV3', 'RapidAI/RapidOCR'} if profile == PADDLE_PROFILE else
           {'docling-project/docling-layout-old', 'docling-project/docling-models',
            'docling-project/CodeFormulaV2', 'RapidAI/RapidOCR'} if profile == DOCLING_PROFILE else set())
    return [r for r in lock['repositories'] if r['repo_id'] in ids]


def download_spec(profile):
    """Flatten pinned native or VLM manifests into safe cache-relative files."""
    from .models import LOCK_PATH
    if profile in VLM_PROFILES:
        model = vlm_model(profile)
        prefix = model['repo'].replace('/', '--') + '/' + model['revision']
        return [{'path': prefix + '/' + f['path'], 'size': f['size'], 'sha256': f['sha256'],
                 'url': f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{f['path']}"}
                for f in model['files']]
    result = []
    for repo in repositories(profile, strict_loads(LOCK_PATH.read_bytes())):
        base = repo.get('download_base', f"https://huggingface.co/{repo['repo_id']}/resolve/{repo['revision']}/")
        result.extend({'path': repo['local_directory'] + '/' + f['path'], 'size': f['byte_size'],
                       'sha256': f['sha256'], 'url': base + f['path']} for f in repo['files'])
    return result


def manifest_id(profile):
    return digest(download_spec(profile))


def public_models():
    result = []
    for row in PARSER_PROFILES:
        spec = download_spec(row['id'])
        model = vlm_model(row['id']) if row['id'] in VLM_PROFILES else {}
        result.append({**row, 'download_bytes': sum(f['size'] for f in spec),
                       'revision': model.get('revision'), 'license': model.get('license'),
                       'manifest_id': digest(spec)})
    return result
