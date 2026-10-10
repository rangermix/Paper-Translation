from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from packages.local_models.catalog import artifact, get_model, public_models
from packages.resources.models import GIB, reference, task_model, vllm_fraction
from packages.resources.policy import ResourcePolicy, policy
from packages.resources.scheduler import admission, limits


def capacity(**changes):
    return {'ram_total_bytes': 64 * GIB, 'ram_used_bytes': 8 * GIB,
            'vram_total_bytes': 24 * GIB, 'vram_used_bytes': 2 * GIB,
            'resident_models': [], 'inventory_complete': True, **changes}


def row(owner='one', model='hy-mt2-7b-q4-k-m-gguf', kind='translate'):
    profile = {'api_protocol': 'local_translation', 'model_id': artifact(get_model(model))['id'], 'local_backend': 'llama.cpp'} if model else {}
    return owner, SimpleNamespace(payload={'profile': profile}), SimpleNamespace(kind=kind, payload={'unit': {}})


def test_defaults_and_strict_policy_validation():
    assert policy() == dict(max_ram_percent=80, max_vram_percent=80, master_concurrency=2, subjob_concurrency=1, auto_concurrency=True)
    for change in [{'max_ram_percent': 101}, {'max_vram_percent': 0}, {'master_concurrency': 0},
                   {'subjob_concurrency': 9}, {'auto_concurrency': 'true'}, {'max_ram_percent': True}, {'extra': 1}]:
        with pytest.raises(ValidationError):
            ResourcePolicy(**change)


def test_catalog_reference_counts_gguf_weights_and_full_context_once():
    ref = reference(get_model('hy-mt2-7b-q4-k-m-gguf'))
    assert ref['weights_bytes'] == 4624648896
    assert ref['kv_cache_bytes'] == GIB and ref['context_tokens'] == 8192
    assert ref['vram_bytes'] == ref['weights_bytes'] + 2 * GIB
    assert all(m['memory_reference']['kind'] == 'estimate' for m in public_models(purpose='all'))


def test_same_resident_model_is_not_reserved_twice_but_distinct_model_is():
    first, second = row(), row('two')
    ident = task_model(first[1], first[2])['id']
    snapshot = capacity(vram_used_bytes=14 * GIB, resident_models=[ident])
    assert admission(policy(), snapshot, [first], second) is None
    assert admission(policy(), snapshot, [first], row('two', 'milmmt-46-12b-q4-k-m-gguf')) == 'VRAM_BUDGET_LIMIT'


def test_loading_reservations_prevent_simultaneous_overcommit():
    snapshot = capacity(vram_used_bytes=8 * GIB)
    assert admission(policy(), snapshot, [], row()) is None
    assert admission(policy(), snapshot, [row()], row('two', 'milmmt-46-4b-q4-k-m-gguf')) == 'VRAM_BUDGET_LIMIT'


def test_asynchronous_preload_retains_budget_after_prepare_job_finishes():
    ident = artifact(get_model('hy-mt2-7b-q4-k-m-gguf'))['id']
    snapshot = capacity(vram_used_bytes=8 * GIB, loading_models=[ident])
    assert admission(policy(), snapshot, [], row('two', 'milmmt-46-4b-q4-k-m-gguf')) == 'VRAM_BUDGET_LIMIT'


def test_budgets_apply_even_when_auto_concurrency_disabled():
    saved = policy() | {'auto_concurrency': False, 'master_concurrency': 8, 'subjob_concurrency': 8}
    assert admission(saved, capacity(ram_used_bytes=55 * GIB), [], row(model=None)) == 'RAM_BUDGET_LIMIT'
    assert admission(saved, capacity(vram_used_bytes=20 * GIB), [], row()) == 'VRAM_BUDGET_LIMIT'


def test_missing_gpu_capacity_waits_without_guessing():
    snapshot = capacity(vram_total_bytes=None, vram_used_bytes=None)
    assert admission(policy(), snapshot, [], row()) == 'RESOURCE_TELEMETRY_UNAVAILABLE'
    assert admission(policy(), snapshot, [], row(model=None)) is None


def test_manual_and_auto_ceilings_and_global_worker_cap():
    saved = policy() | {'master_concurrency': 8, 'subjob_concurrency': 8}
    constrained = capacity(ram_used_bytes=49 * GIB, vram_used_bytes=19 * GIB)
    assert limits(saved, constrained) == (1, 1)
    assert limits(saved | {'auto_concurrency': False}, constrained) == (8, 8)
    active = [row(str(i // 8), model=None) for i in range(16)]
    assert admission(saved | {'auto_concurrency': False}, capacity(), active, row('3', model=None)) == 'MASTER_CONCURRENCY_LIMIT'


def test_master_and_subjob_limits_are_independent():
    saved = policy() | {'master_concurrency': 1, 'subjob_concurrency': 2}
    assert admission(saved, capacity(), [row(model=None)], row('two', model=None)) == 'MASTER_CONCURRENCY_LIMIT'
    assert admission(saved, capacity(), [row(model=None)], row(model=None)) is None
    assert admission(saved, capacity(), [row(model=None), row(model=None)], row(model=None)) == 'SUBJOB_CONCURRENCY_LIMIT'


def test_vllm_startup_budget_is_model_sized(monkeypatch):
    monkeypatch.setattr('packages.resources.telemetry.capacity', capacity)
    from packages.parsers.catalog import vlm_model
    model = vlm_model('infinity-parser2-flash-v1')
    assert .3 < float(vllm_fraction(model)) < .5


def test_analyst_uses_frozen_selection_and_unified_memory():
    analyst = get_model('minicpm5-1b-q4')
    candidate = row()
    candidate[1].payload.update(preparation_options={'mode': 'local'}, analysis_profile={
        'api_protocol': 'local_analysis', 'model_id': artifact(analyst)['id'], 'local_backend': 'mlx'})
    candidate[2].payload = {'phase': 'preparation'}
    assert task_model(candidate[1], candidate[2])['id'] == artifact(analyst)['id']
    assert admission(policy(), capacity(vram_total_bytes=None, vram_used_bytes=None), [], candidate) is None


def test_parallel_inference_holds_off_model_reconfiguration():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from packages.local_models.service import InferenceGate
    gate = InferenceGate()
    ready = threading.Barrier(3)
    release = threading.Event()
    configured = threading.Event()
    def infer():
        with gate.shared():
            ready.wait(timeout=2)
            assert release.wait(2)
    def configure():
        with gate:
            configured.set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        first, second = pool.submit(infer), pool.submit(infer)
        ready.wait(timeout=2)
        third = pool.submit(configure)
        assert not configured.wait(.05)
        release.set()
        first.result()
        second.result()
        third.result()
    assert configured.is_set()
