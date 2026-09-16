"""Export verified, already bundled model files; never download at runtime."""
import argparse
import os
import shutil
from pathlib import Path

from packages.parsers.models import verify_models
from packages.parsers.profiles import PADDLE_MODEL


def export_model(root, destination):
    root, destination = Path(root), Path(destination)
    lock = verify_models(root)
    model = next(repo for repo in lock['repositories'] if repo['repo_id'] == PADDLE_MODEL)
    if destination.exists():
        raise ValueError('MODEL_EXPORT_DESTINATION_EXISTS')
    destination.mkdir(parents=True)
    for entry in model['files']:
        target = destination / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / model['local_directory'] / entry['path'], target)
    # All exported bytes have already been checked against the repository lock.
    return model['revision']


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--destination', required=True)
    args = cli.parse_args()
    print(export_model(os.environ.get('DOCLING_ARTIFACTS_PATH', '/opt/docling/models'), args.destination))
