"""Run inside the pinned CUDA runner image, without a GPU or model weights.

Verifies the actual upstream allocator after the image-build patch, including
hybrid attention padding, rather than reproducing the patch's arithmetic.
"""
from types import SimpleNamespace

import torch
from vllm.v1.core.kv_cache_utils import (
    _max_memory_usage_bytes_from_groups, get_kv_cache_config_from_groups,
)
from vllm.v1.kv_cache_interface import FullAttentionSpec, KVCacheGroupSpec, SlidingWindowSpec


cfg = SimpleNamespace(
    model_config=SimpleNamespace(max_model_len=8192),
    scheduler_config=SimpleNamespace(max_num_seqs=1, max_num_batched_tokens=2048),
    cache_config=SimpleNamespace(num_gpu_blocks_override=None),
    parallel_config=SimpleNamespace(decode_context_parallel_size=1, prefill_context_parallel_size=1))
full = FullAttentionSpec(block_size=16, num_kv_heads=4, head_size=128, dtype=torch.float16)
sliding = SlidingWindowSpec(block_size=16, num_kv_heads=4, head_size=128, dtype=torch.float16, sliding_window=4096)
available = 20 * 1024**3
for groups in ([KVCacheGroupSpec(['full.0', 'full.1'], full)],
               [KVCacheGroupSpec(['full.0', 'full.1'], full), KVCacheGroupSpec(['sliding.0'], sliding)]):
    required = _max_memory_usage_bytes_from_groups(cfg, groups)
    null_page = max(len(group.layer_names) for group in groups) * full.page_size_bytes
    configured = get_kv_cache_config_from_groups(cfg, groups, available)
    allocated = sum(tensor.size for tensor in configured.kv_cache_tensors)
    assert allocated == required + null_page, (allocated, required, null_page)
    assert allocated < available // 10
    print({'groups': len(groups), 'required_bytes': required, 'allocated_bytes': allocated,
           'num_blocks': configured.num_blocks})
cfg.scheduler_config.max_num_seqs = 2
unbounded = get_kv_cache_config_from_groups(cfg, [KVCacheGroupSpec(['full.0', 'full.1'], full)], available)
assert sum(tensor.size for tensor in unbounded.kv_cache_tensors) == available
assert get_kv_cache_config_from_groups(cfg, [], available).num_blocks == 1
print('Pinned vLLM cache allocation checks passed')
