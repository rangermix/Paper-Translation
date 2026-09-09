"""Reproduce the PostgreSQL queue ordering relevant to worker maintenance locks."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
import threading
import time
import psycopg


def main():
    url = os.environ['TEST_DATABASE_URL'].replace('postgresql+psycopg:', 'postgresql:')
    # Dedicated key: no application lock or schema/data is changed.
    key = 742095418
    with psycopg.connect(url, autocommit=True) as guard, psycopg.connect(url, autocommit=True) as maintenance, psycopg.connect(url, autocommit=True) as write:
        guard.execute('select pg_advisory_lock_shared(%s)', (key,))
        waiter = threading.Thread(target=lambda: maintenance.execute('select pg_advisory_lock(%s)', (key,)))
        waiter.start()
        time.sleep(.2)
        write.execute('set lock_timeout=500')
        try:
            write.execute('select pg_advisory_lock_shared(%s)', (key,))
            outcome = 'acquired'
        except psycopg.errors.LockNotAvailable:
            outcome = 'blocked_by_waiting_exclusive'
        finally:
            guard.execute('select pg_advisory_unlock_shared(%s)', (key,))
            waiter.join(timeout=3)
            maintenance.execute('select pg_advisory_unlock(%s)', (key,))
        print(json.dumps({'second_worker_connection': outcome,
            'implication': 'A queued exclusive lock can block an existing worker using another connection; avoid queueing it while shared guards exist.'}))


if __name__ == '__main__':
    main()
