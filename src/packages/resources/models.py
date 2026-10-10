"""Conservative planning references, not measured peaks or model capabilities.

Weight bytes come from locked files. KV references assume unquantized FP16 at
the configured context. Working-space allowances cover loading and inference.
The same references drive the UI and scheduling; one resident model is counted
once, irrespective of the number of jobs using it.
"""
import math

GIB = 1024 ** 3
# GiB of cache at the catalogue's configured context. Unknown architectures use
# a deliberately conservative estimate. These values are not measured peaks.
KV_GIB = {
    'hy-mt2-7b-q4-k-m-gguf': 1.0, 'hy-mt2-7b-q4': 1.0,
    'hy-mt2-1.8b-q4-k-m-gguf': .5, 'hy-mt2-1.8b-q8': .5,
    'hy-mt2-1.8b-bf16-vllm': .5,
    'infinity-parser2-flash-v1': 1.5,
}


def reference(model, backend=None):
    backend = backend or model.get('runtime', 'vllm')
    parser = model['id'].endswith('-v1')
    weights = sum(f['size'] for f in model['files']
                  if f['path'].endswith(('.gguf', '.safetensors')))
    kv = math.ceil(KV_GIB.get(model['id'], 4.0 if parser else 2.0) * GIB)
    workspace = (3 if parser else 1) * GIB
    vram = weights + kv + workspace
    ram = weights + (4 if parser else 2) * GIB
    # Unified memory must not be added to itself as RAM plus VRAM.
    if backend == 'mlx':
        ram = max(ram, vram)
    return {'kind': 'estimate', 'weights_bytes': weights, 'kv_cache_bytes': kv,
            'workspace_bytes': workspace, 'ram_bytes': ram, 'vram_bytes': vram,
            'context_tokens': model['context_size'], 'shared_weights': True,
            'unified_memory': backend == 'mlx', 'basis': 'locked_weights_fp16_context_with_headroom'}


def vllm_fraction(model):
    from .telemetry import capacity
    total = capacity().get('vram_total_bytes')
    if not total:
        return '0.8'  # The managed CUDA engine still caps KV allocation itself.
    return str(min(.8, max(.05, math.ceil(reference(model)['vram_bytes'] / total * 1000) / 1000)))


def _task_model(job, task):
    """Resolve only frozen task identities. Never consult the current provider."""
    from packages.local_models.catalog import artifact, get_model
    from packages.parsers.catalog import vlm_model
    payload = job.payload or {}
    if task.kind in ('parse', 'prepare_parser_model'):
        model = vlm_model(task.payload.get('parser_profile_revision') or payload.get('parser_profile_revision'))
        backend = task.payload.get('backend') or task.payload.get('parser_backend', payload.get('parser_backend', 'vllm'))
    elif task.kind == 'prepare_local_model':
        model = get_model(task.payload['model_id'])
        backend = task.payload['backend']
    else:
        profile = payload.get('profile', {})
        if payload.get('preparation_options', {}).get('mode') == 'local':
            # Planning may prepare the analyst before translation units exist.
            if task.payload.get('phase') == 'preparation' or 'unit' not in task.payload:
                profile = payload.get('analysis_profile') or profile
        if profile.get('api_protocol') not in ('local_translation', 'local_analysis'):
            return None
        model = get_model(profile['model_id'])
        backend = profile.get('local_backend') or model['runtime']
    return {'id': artifact(model)['id'], 'backend': backend, **reference(model, backend)}


def task_model(job, task):
    try:
        return _task_model(job, task)
    except (ValueError, KeyError, TypeError, StopIteration):
        # Legacy/invalid selections must reach their normal execution validator,
        # which rejects them before inference, rather than wedging the queue.
        return None
