"""Explicit simulated completed response lost at SIGKILL, then user-authorized retry."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import json
import os
from pathlib import Path
import time

from packages.providers.fake import FakeProvider
import packages.translation.execution as execution
from workers.main import main

OUT = Path('/evidence')


def durable(name, value):
    with (OUT / name).open('w') as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


class CountingFake(FakeProvider):
    def translate(self, *args, **kwargs):
        response = super().translate(*args, **kwargs)
        path = OUT / 'fake-provider-counter.json'
        previous = json.loads(path.read_text())['calls'] if path.exists() else 0
        durable(path.name, {'calls': previous + 1, 'usage_kind': 'simulated, not supplier billing'})
        return response


provider = CountingFake()
original_execute = execution.execute_translation
original_settle = execution.settle


def execute(*args, **kwargs):
    return original_execute(*args, provider=provider, **kwargs)


def settle(*args, **kwargs):
    if not (OUT / 'translation-kill-barrier.json').exists():
        durable('translation-kill-barrier.json', {'window': 'after-response', 'at': time.time(),
            'provider_kind': 'explicit FakeProvider; no real supplier execution'})
        while True:
            time.sleep(.1)
    return original_settle(*args, **kwargs)


execution.execute_translation = execute
execution.settle = settle

if __name__ == '__main__':
    main()
