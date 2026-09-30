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
print(json.dumps({'vllm': vllm.__version__, 'torch': torch.__version__,
                  'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0),
                  'cuda_execution': 'ok'}), flush=True)
