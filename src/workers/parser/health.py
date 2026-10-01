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
    if heartbeat.get('service_ready') is not True and heartbeat.get('models_verified') is not True:
        raise SystemExit('parser service not ready')
    if heartbeat.get('memory_limit_bytes') != memory_limit:raise SystemExit('parser memory envelope changed')
    # Selected weights are verified on use. Probes never prepare models.


if __name__=='__main__':main()
