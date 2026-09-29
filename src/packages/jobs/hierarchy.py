"""Separate main operations from their internal steps without rewriting history."""
from sqlalchemy import and_, case, func, or_, select

from packages.domain.models import Job, Permit, Task
from .visibility import finished_history, visible_history


MAIN_STAGES = {'parse', 'translate', 'candidate', 'semantic_review', 'publish',
               'rebuild', 'export', 'cleanup', 'provider_test'}


def main_task():
    # Old parent links record both containment and follow-up operations. An
    # unowned historical step remains readable until its owner can be proven.
    return or_(Job.parent_job_id.is_(None), Job.stage.in_(MAIN_STAGES))


def task_role(job):
    return 'main' if job.parent_job_id is None or job.stage in MAIN_STAGES else 'step'


STATUSES = ('outcome_unknown', 'failed', 'waiting_budget', 'waiting_config', 'needs_review',
            'paused', 'cancel_requested', 'running', 'pending', 'partially_completed',
            'completed_with_warnings', 'cancelled', 'succeeded')


def operation():
    return func.coalesce(Job.config_snapshot['operation'].astext, Job.payload['operation'].astext,
        case((and_(Job.stage == 'inspect', Job.payload['upload_id'].astext.is_not(None)), 'upload'), else_=Job.stage))


def family_tree(root_ids=None):
    roots = select(Job.id.label('root_id'), Job.id.label('job_id'))
    roots = roots.where(main_task()) if root_ids is None else roots.where(Job.id.in_(root_ids))
    tree = roots.cte('job_family_tree', recursive=True)
    # UNION also bounds traversal if an old, malformed family contains a cycle.
    return tree.union(select(tree.c.root_id, Job.id).join(tree, Job.parent_job_id == tree.c.job_id).where(~main_task()))


def family_summary(root_ids=None, *, stage=None, model=None, tree=None):
    if tree is None:
        tree = family_tree(root_ids)
    unknown = select(Permit.id).where(Permit.job_id == Job.id, Permit.state == 'unknown').correlate(Job).exists()
    reserved = select(Permit.id).where(Permit.job_id == Job.id, Permit.state == 'reserved').correlate(Job).exists()
    leased = select(Task.id).where(Task.job_id == Job.id, Task.status == 'leased').correlate(Job).exists()
    rank = {value: priority for priority, value in enumerate(STATUSES)}
    priority = case(
        (unknown, rank['outcome_unknown']),
        (or_(reserved, leased), rank['running']),
        (and_(Job.id != tree.c.root_id, Job.stage.in_(['quality_check', 'recovery', 'metadata_lookup']),
              Job.status == 'failed'), rank['completed_with_warnings']),
        (Job.status == 'queued', rank['pending']),
        (Job.status == 'translating', rank['running']),
        (Job.status == 'waiting_configuration', rank['waiting_config']),
        (Job.status == 'completed', rank['succeeded']),
        else_=case(*[(Job.status == value, weight) for value, weight in rank.items()], else_=rank['needs_review']))
    columns = [tree.c.root_id, func.count().label('job_count'),
        func.bool_and(finished_history()).label('finished'),
        func.bool_or(visible_history()).label('visible'), func.min(priority).label('priority')]
    if stage:
        columns.append(func.bool_or(or_(Job.stage == stage, operation() == stage)).label('matches_stage'))
    if model:
        from sqlalchemy import cast, Text
        columns.append(func.bool_or(cast(Job.actual_model, Text).icontains(model, autoescape=True)).label('matches_model'))
    totals = select(*columns).join(tree, tree.c.job_id == Job.id).group_by(tree.c.root_id).subquery('job_family_totals')
    return select(*(column for column in totals.c if column.name != 'priority'),
        case(*[(totals.c.priority == rank, value) for rank, value in enumerate(STATUSES)], else_='needs_review').label('status')
    ).subquery('job_families')


def family_views(session, job_ids):
    if not job_ids:
        return {}
    summary = family_summary(job_ids)
    return {row.root_id: {'status': row.status, 'job_count': row.job_count}
            for row in session.execute(select(summary))}


def job_operation(job):
    return ((job.config_snapshot or {}).get('operation') or job.payload.get('operation')
            or ('upload' if job.stage == 'inspect' and job.payload.get('upload_id') else job.stage))
