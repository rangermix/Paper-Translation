"""Build-time patch, fail closed if the pinned backend layout changes."""
import importlib.util
import json
from pathlib import Path

root = Path('/vllm-metal/lib/python3.12/site-packages')
adapter = root / 'vllm_metal/v1/model_adapter.py'
source = adapter.read_text()
anchor = '        model_type_from_hf = hf_config.model_type\n        if model_type_from_hf in _TEXT_BACKBONE_OVERRIDE_TYPES:'
assert source.count(anchor) == 1, 'Backend adapter changed; review the MLX text-loader patch.'
source = source.replace(anchor, '        model_type_from_hf = hf_config.model_type\n'
    '        if model_type_from_hf == "gemma3" and self._has_mlx_quantized_weights(hf_config):\n'
    '            return True\n        if model_type_from_hf in _TEXT_BACKBONE_OVERRIDE_TYPES:')
adapter.write_text(source)
spec = importlib.util.spec_from_file_location('catalog', '/catalog/catalog.py')
catalog = importlib.util.module_from_spec(spec); spec.loader.exec_module(catalog)
(root / 'translation_model_ids.json').write_text(json.dumps([catalog.artifact(m)['id'] for m in catalog.models()]))
startup = root / 'sitecustomize.py'
startup.write_text(startup.read_text() + '\nimport translation_startup\n')
cache = root / 'vllm_metal/v1/cache_policy.py'
source = cache.read_text()
anchor = '        kv_budget = base_kv_budget - reservation.total_bytes - draft_scratch_bytes\n'
assert source.count(anchor) == 1, 'Backend cache planner changed; review bounded allocation.'
source = source.replace(anchor, anchor +
    '        from translation_startup import bounded_cache_budget\n'
    '        kv_budget = bounded_cache_budget(self._worker.model_config.served_model_name,\n'
    '            self._worker.model_config.max_model_len, block_size, per_block_bytes, kv_budget)\n')
cache.write_text(source)
