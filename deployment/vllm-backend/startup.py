"""Validate the CUDA runtime before exposing DMR; no model or content requests."""
import json

import torch
import vllm
from vllm.platforms import current_platform

if not torch.cuda.is_available() or not current_platform.is_cuda():
    raise RuntimeError('CUDA vLLM is unavailable on this deployment')
result = (torch.ones(4, device='cuda') * 2).tolist()
if result != [2.0] * 4:
    raise RuntimeError('CUDA execution check failed')
# Elementwise operations do not exercise cuBLAS. The vision patch projection
# uses linear with bias, so check that path before accepting model requests.
for dtype in (torch.bfloat16, torch.float16):
    inputs = torch.ones((64, 1536), device='cuda', dtype=dtype)
    weights = torch.ones((1152, 1536), device='cuda', dtype=dtype)
    bias = torch.ones(1152, device='cuda', dtype=dtype)
    projected = torch.nn.functional.linear(inputs, weights, bias)
    # BF16 rounds 1537 to 1536; compare with the same output representation.
    expected = torch.full_like(projected, 1537)
    if not torch.equal(projected, expected):
        raise RuntimeError(f'CUDA linear execution check failed for {dtype}')
print(json.dumps({'vllm': vllm.__version__, 'torch': torch.__version__,
                  'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0),
                  'cuda_execution': 'ok',
                  'cuda_linear': ['bfloat16', 'float16']}), flush=True)
