"""Bound vLLM 0.19.1 single-request KV allocation at image build time.

Use vLLM's own group-aware calculation (including hybrid/sliding attention),
plus a null block. Fail the build when the pinned upstream function changes.
"""
from pathlib import Path

NEEDLE = '    # Determine how model runners should initialize the KV cache tensors.\n'
REPLACEMENT = '''    # Paper Translation runs bounded single-request engines. Reserve one full
    # context plus the allocator's null block, not all otherwise available VRAM.
    if vllm_config.scheduler_config.max_num_seqs == 1:
        if len(kv_cache_groups) == 1 and isinstance(kv_cache_groups[0].kv_cache_spec, UniformTypeKVCacheSpecs):
            pool_page_bytes = kv_cache_groups[0].kv_cache_spec.page_size_bytes
        else:
            pool_page_bytes = max(len(group.layer_names) for group in kv_cache_groups) * get_uniform_page_size(
                [group.kv_cache_spec for group in kv_cache_groups])
        bounded_bytes = _max_memory_usage_bytes_from_groups(vllm_config, kv_cache_groups) + pool_page_bytes
        available_memory = min(available_memory, bounded_bytes)
        logger.info("Paper Translation bounded KV cache: %.3f GiB", available_memory / (1024 ** 3))

''' + NEEDLE


def patch(path):
    content = path.read_text()
    if content.count(NEEDLE) != 1 or 'Paper Translation bounded KV cache' in content:
        raise RuntimeError('Pinned vLLM cache implementation changed')
    path.write_text(content.replace(NEEDLE, REPLACEMENT))


if __name__ == '__main__':
    patch(Path('/opt/vllm-env/lib/python3.12/site-packages/vllm/v1/core/kv_cache_utils.py'))
