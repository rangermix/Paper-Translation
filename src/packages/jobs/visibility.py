"""Task-list visibility never deletes execution or billing records."""
from sqlalchemy import and_, or_, select

from packages.domain.models import Job, Permit, Task
from packages.domain.workflow import TERMINAL_STATES


def finished_history():
    unsettled = select(Permit.id).where(Permit.job_id == Job.id,
        Permit.state.in_(['reserved', 'unknown'])).correlate(Job).exists()
    leased = select(Task.id).where(Task.job_id == Job.id,
        Task.status == 'leased').correlate(Job).exists()
    return and_(Job.status.in_(TERMINAL_STATES), ~unsettled, ~leased)


def clearable_history():
    return and_(finished_history(),
                Job.history_cleared_generation.is_distinct_from(Job.generation))


def visible_history():
    # Changed jobs and unresolved work must stay discoverable, even if a marker
    # was recorded before a later worker update or billing reconciliation.
    return or_(Job.history_cleared_generation.is_distinct_from(Job.generation),
               ~finished_history())
