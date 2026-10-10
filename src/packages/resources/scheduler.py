"""Admission budgets for the whole instance, before model preparation/dispatch.

This is a scheduler guard, not an OS quota: other programs can allocate memory
after a sample. Existing work is never killed to satisfy a changed setting.
"""
from .models import GIB, loading_reference, task_model
from .policy import WORKER_LIMIT


def owner(session, job):
    from packages.domain.models import Job
    from packages.jobs.hierarchy import MAIN_STAGES
    visited = set()
    while job.parent_job_id and job.stage not in MAIN_STAGES and job.id not in visited:
        visited.add(job.id)
        parent = session.get(Job, job.parent_job_id)
        if parent is None:
            break
        job = parent
    return job.id


def limits(policy, capacity):
    """Auto mode derives ceilings from remaining budget; admission checks below.

    Reserve 2 GiB per document workflow and 256 MiB per worker. Model allocations
    are accounted separately, using their frozen selection and residency.
    """
    masters, children = policy['master_concurrency'], policy['subjob_concurrency']
    if policy['auto_concurrency'] and capacity is not None:
        total = (capacity or {}).get('ram_total_bytes')
        if not total or capacity.get('ram_used_bytes') is None:
            return 1, 1
        budget = max(0, total * policy['max_ram_percent'] / 100 - capacity.get('ram_used_bytes', 0))
        masters = max(1, min(masters, int(budget // (2 * GIB))))
        children = max(1, min(children, int(budget // (masters * GIB / 4))))
        if capacity.get('vram_total_bytes') and capacity.get('vram_used_bytes') is not None:
            gpu_free = max(0, capacity['vram_total_bytes'] * policy['max_vram_percent'] / 100 - capacity['vram_used_bytes'])
            children = max(1, min(children, int(gpu_free // (GIB / 8))))
    return masters, min(children, WORKER_LIMIT)


def admission(policy, capacity, active, candidate):
    """Rows are (owner id, Job, Task). Return a stable waiting reason or None."""
    masters, children = limits(policy, capacity)
    root, job, task = candidate
    roots = {row[0] for row in active}
    if len(active) >= WORKER_LIMIT or (root not in roots and len(roots) >= masters):
        return 'MASTER_CONCURRENCY_LIMIT'
    if sum(row[0] == root for row in active) >= children:
        return 'SUBJOB_CONCURRENCY_LIMIT'
    # The parser spool is serial, so a second parse must not occupy a master
    # slot or reserve a second model while waiting for the parser process.
    if task.kind in ('parse', 'inspect') and any(row[2].kind in ('parse', 'inspect') for row in active):
        return 'PARSER_CONCURRENCY_LIMIT'
    if capacity is None:  # Explicit dependency injection for queue contract tests.
        return None
    model = task_model(job, task)
    if model and not model['unified_memory'] and not capacity.get('vram_total_bytes'):
        return 'RESOURCE_TELEMETRY_UNAVAILABLE'
    if not capacity.get('ram_total_bytes'):
        return 'RESOURCE_TELEMETRY_UNAVAILABLE'
    models = {}
    ram_extra = 0
    for _, current_job, current_task in [*active, candidate]:
        ram_extra += 2 * GIB if current_task.kind in ('parse', 'inspect') else GIB // 4
        selected = task_model(current_job, current_task)
        if selected:
            models[selected['id']] = selected
    resident = set(capacity.get('resident_models', []))
    for ident in capacity.get('loading_models', []):
        pending = loading_reference(ident)
        if pending:
            models[ident] = pending
    # Small per-request scratch allowance is separate from the shared KV pool.
    vram_extra = sum(GIB // 8 for _, j, t in [*active, candidate]
                     if (selected := task_model(j, t)) and not selected['unified_memory'])
    for ident, selected in models.items():
        if ident not in resident:
            ram_extra += selected['ram_bytes']
            if not selected['unified_memory']:
                vram_extra += selected['vram_bytes']
    for resource, extra in [('ram', ram_extra), ('vram', vram_extra)]:
        total, used = capacity.get(resource + '_total_bytes'), capacity.get(resource + '_used_bytes')
        if total is None or used is None:
            if resource == 'ram' or extra:
                return 'RESOURCE_TELEMETRY_UNAVAILABLE'
            continue
        if used + extra > total * policy['max_' + resource + '_percent'] / 100:
            return 'RAM_BUDGET_LIMIT' if resource == 'ram' else 'VRAM_BUDGET_LIMIT'
    return None
