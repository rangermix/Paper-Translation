import os
import time
from pathlib import Path
from packages.ir import strict_loads
from workers.parser.main import verify_memory_envelope


def main():
    memory_limit = verify_memory_envelope()
    root=Path(os.environ.get('PARSER_OUTPUTS','/outputs'))
    heartbeat=strict_loads((root/'heartbeat.json').read_bytes())
    if time.time()-heartbeat['timestamp']>30:raise SystemExit('parser heartbeat stale')
    if heartbeat.get('models_verified') is not True:raise SystemExit('parser models not verified')
    if heartbeat.get('memory_limit_bytes') != memory_limit:raise SystemExit('parser memory envelope changed')
    # ModelHealth verifies the immutable image weights at startup and every
    # sixty seconds, revoking this heartbeat on failure. Rehashing gigabytes in
    # each probe can exceed Docker's health timeout during otherwise valid work.


if __name__=='__main__':main()
