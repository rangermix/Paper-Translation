"""A real PostgreSQL concurrency regression found during independent review."""
import os
import threading
import time

import pytest
from sqlalchemy import create_engine, text

from packages.maintenance.__main__ import acquire_maintenance_lock


@pytest.mark.skipif(not os.environ.get('ACCEPTANCE_DATABASE_URL'), reason='Dedicated PostgreSQL acceptance database required')
def test_draining_maintenance_does_not_block_existing_workers_other_connection():
    engine=create_engine(os.environ['ACCEPTANCE_DATABASE_URL'])
    acquired=threading.Event()
    release=threading.Event()
    errors=[]
    with engine.connect() as guard, engine.connect() as writer:
        guard.execute(text('SELECT pg_advisory_lock_shared(798205424)'))
        guard.commit()
        def maintenance():
            try:
                with engine.connect() as connection:
                    acquire_maintenance_lock(connection)
                    acquired.set()
                    release.wait(timeout=4)
                    connection.execute(text('SELECT pg_advisory_unlock(798205424)'))
                    connection.commit()
            except BaseException as error:
                errors.append(error)
        thread=threading.Thread(target=maintenance,daemon=True)
        thread.start()
        try:
            time.sleep(.3)
            assert not acquired.is_set(), 'maintenance must drain the existing worker'
            writer.execute(text("SET lock_timeout='1000ms'"))
            writer.execute(text('SELECT pg_advisory_xact_lock_shared(798205424)'))
            writer.commit()
            guard.execute(text('SELECT pg_advisory_unlock_shared(798205424)'))
            guard.commit()
            assert acquired.wait(timeout=3), 'maintenance should acquire after the worker exits'
        finally:
            guard.execute(text('SELECT pg_advisory_unlock_all()'))
            guard.commit()
            release.set()
            thread.join(timeout=4)
        assert not thread.is_alive()
        assert not errors
    engine.dispose()
