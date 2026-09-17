"""CLI operation receipts survive failures and restore replacing the database."""
from contextlib import contextmanager

from packages.domain.models import now
from packages.jobs.stages import completed_stage


@contextmanager
def operation_receipt(db, operation):
    started, code = now(), None
    try:
        yield
    except Exception as exc:
        code = getattr(exc, 'code', 'MAINTENANCE_FAILED')
        raise
    finally:
        finished = now()
        # Store after pg_restore, in the database that actually remains active.
        # A backup consequently contains only operations committed before its
        # snapshot, not a misleading running receipt for the backup itself.
        try:
            db.ready()
        except Exception:
            pass  # An unavailable/old database cannot accept a new-schema receipt.
        else:
            with db.transaction() as session:
                completed_stage(session, stage=operation if operation in {'backup', 'restore'} else 'maintenance',
                    started_at=started, finished_at=finished, status='failed' if code else 'succeeded',
                    payload={'operation': operation}, result={'operation': operation}, code=code)
