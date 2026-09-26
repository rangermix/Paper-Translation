"""Pinned local models and deterministic Docker Model Runner identities."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

ENDPOINT = 'http://local-translator:8090/v1/completions'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


@lru_cache
def models():
    return json.loads(Path(__file__).with_name('models.lock.json').read_text())['models']


def artifact(model):
    layers = [{'mediaType': 'application/vnd.docker.ai.' + ('safetensors' if f['path'].endswith('.safetensors') else 'chat.template.jinja' if f['path'].endswith('.jinja') else 'model.file'),
               'digest': 'sha256:' + f['sha256'], 'size': f['size'],
               'annotations': {'org.cncf.model.filepath': f['path']}} for f in model['files']]
    config = encoded({'config': {'format': model['format'], 'quantization': f"MLX{model['bits']}",
        'context_size': model['context_size']}, 'descriptor': {'created': '2026-09-15T00:00:00Z'},
        'rootfs': {'type': 'layers', 'diff_ids': [layer['digest'] for layer in layers]}})
    manifest = encoded({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'config': {'mediaType': 'application/vnd.docker.ai.model.config.v0.2+json',
                   'digest': 'sha256:' + sha(config), 'size': len(config)}, 'layers': layers})
    return {'id': 'sha256:' + sha(manifest), 'config': config, 'manifest': manifest}


def get_model(identifier):
    for model in models():
        if identifier in (model['id'], artifact(model)['id']):
            return model
    raise ValueError('LOCAL_MODEL_UNKNOWN')


def public_models(*, purpose='translation'):
    if purpose not in ('translation', 'analysis', 'all'):
        raise ValueError('LOCAL_MODEL_PURPOSE')
    return [{**{key: m[key] for key in ('id', 'label', 'family', 'bits', 'runtime', 'repo', 'revision', 'license', 'context_size')},
             'model_id': artifact(m)['id'], 'download_bytes': sum(f['size'] for f in m['files'])}
            for m in models() if purpose == 'all' or m.get('purpose', 'translation') == purpose]
