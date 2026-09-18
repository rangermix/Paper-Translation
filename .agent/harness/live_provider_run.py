"""Default-off, one-use authorization for the eight controlled external-test blocks."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
    from ._compose import provider_override
else:
    from _project import ROOT, artifact_path, output_path
    from _compose import provider_override
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid


sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / 'tests/fixtures/live-provider/manifest.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_recorded_command(argv, *, env, commands, evidence_path, timeout=900):
    """Persist a redacted outcome even when an interrupted child returned only bytes."""
    from harness.acceptance import redact

    def public_text(value):
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='replace')
        return redact(value or '')

    started = time.monotonic()
    try:
        completed = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as error:
        commands.append({'argv': [redact(str(arg)) for arg in argv], 'status': 'timed_out',
            'exit_code': None, 'timeout_seconds': timeout, 'duration_seconds': round(time.monotonic() - started, 3),
            'stdout': public_text(error.stdout), 'stderr': public_text(error.stderr)})
        Path(evidence_path).write_text(json.dumps(commands, indent=2), encoding='utf-8')
        raise RuntimeError('Live command timed out; retained evidence and database state require inspection before any retry.') from None
    commands.append({'argv': [redact(str(arg)) for arg in argv],
        'status': 'completed' if completed.returncode == 0 else 'failed', 'exit_code': completed.returncode,
        'duration_seconds': round(time.monotonic() - started, 3),
        'stdout': public_text(completed.stdout), 'stderr': public_text(completed.stderr)})
    Path(evidence_path).write_text(json.dumps(commands, indent=2), encoding='utf-8')
    if completed.returncode != 0:
        raise RuntimeError('Live run stopped; inspect its retained command evidence before any retry.')
    return completed.stdout


def authorization(path):
    """Validate approval and public metadata without reading a secret or contacting a service."""
    from packages.ir import strict_loads
    from packages.domain.config import validate_public_profile
    def need(condition, message):
        if not condition:
            raise ValueError(message)
    approval = strict_loads(Path(path).read_bytes())
    need(approval.get('approved') is True, 'Explicit external-processing approval is missing.')
    need(re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', approval.get('approval_id', '')), 'A unique approval ID is required.')
    need(approval.get('scope') == 'controlled_eight_blocks_translation_candidate_semantic_review', 'Unexpected approval scope.')
    need(approval.get('manifest_sha256') == sha(MANIFEST), 'Controlled source manifest changed after approval.')
    budget = approval.get('total_budget_micro')
    need(type(budget) is int and budget > 0, 'A positive total USD microcurrency budget is required.')
    profile_path, supplied_key = Path(approval['profile_file']).resolve(), Path(approval['secret_file'])
    need(not supplied_key.is_symlink(), 'Backend secret symlinks are not supported.')
    key_path = supplied_key.resolve()
    need(profile_path.is_file() and key_path.is_file(), 'Backend files are missing.')
    profile_bytes = profile_path.read_bytes()
    need(len(profile_bytes) <= 16384, 'Public Provider profile exceeds the metadata limit.')
    need(approval.get('profile_sha256') == hashlib.sha256(profile_bytes).hexdigest(), 'Public Provider profile changed after approval.')
    profile = validate_public_profile(strict_loads(profile_bytes))
    need(profile.get('semantic_review_enabled') is True, 'The approved semantic-review profile must be explicit.')
    need(set(map(tuple, profile['enabled_pairs'])) == {('en', 'zh-Hans'), ('zh-Hans', 'en')}, 'Only the two approved language pairs may be enabled.')
    manifest = strict_loads(MANIFEST.read_bytes())
    need(len(manifest['documents']) == 2 and {doc['id'] for doc in manifest['documents']} == {'controlled-en', 'controlled-zh'}, 'Unexpected controlled document set.')
    need(sum(len(doc['source_text']) for doc in manifest['documents']) == 8, 'Expected eight controlled source blocks.')
    for doc in manifest['documents']:
        original = artifact_path(doc['path'])
        need(original.resolve().is_relative_to((ROOT / 'tests/fixtures/live-provider').resolve()), 'Source path escapes controlled fixture directory.')
        need(original.is_file() and sha(original) == doc['sha256'], 'Controlled PDF bytes changed.')
    return approval, profile_path, key_path, profile, profile_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--execute', action='store_true', help='Requires existing explicit authorization; may incur paid usage.')
    args = parser.parse_args()
    if args.approval is None:
        print(json.dumps({'status': 'not_authorized', 'network_requests': 0, 'manifest_sha256': sha(MANIFEST),
            'required': ['explicit scope approval', 'fixed public profile and hash', 'backend secret file path', 'total budget', 'unique approval ID'],
            'next': 'Provide the reviewed approval file; execution also requires --execute.'}))
        return
    approval, profile_path, key_path, profile, profile_bytes = authorization(args.approval)
    public = {key: approval[key] for key in ('approval_id', 'scope', 'manifest_sha256', 'profile_sha256', 'total_budget_micro')}
    public.update(model_id=profile['model_id'], profile_revision=profile['profile_revision'])
    if not args.execute:
        print(json.dumps({'status': 'validated_without_execution', 'network_requests': 0, **public}))
        return
    # Never repeat an uncertain or partially paid run under the same approval.
    receipt_dir = ROOT / '.agent/local-data/live-provider'
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = receipt_dir / (approval['approval_id'] + '.used.json')
    with receipt.open('x', encoding='utf-8') as handle:
        json.dump({'status': 'claimed', **public}, handle)
    project = 'bilingual-live-' + uuid.uuid4().hex[:8]
    output = ROOT / '.agent/tmp/evidence/live-provider-runs' / project
    output.mkdir(parents=True)
    frozen_profile = output / 'approved-public-profile.json'
    frozen_profile.write_bytes(profile_bytes)
    (output / 'authorization-scope.json').write_text(json.dumps(public, indent=2))
    override = output / 'override.json'
    injection = provider_override(frozen_profile, key=key_path)
    injection['services']['app']['volumes'] += [
        str(ROOT / '.agent/harness').replace('\\', '/') + ':/harness:ro',
        str(ROOT / 'tests/fixtures/live-provider').replace('\\', '/') + ':/controlled:ro',
        str(output).replace('\\', '/') + ':/live-evidence']
    override.write_text(json.dumps(injection, indent=2))
    env = {**os.environ, "COMPOSE_PROFILES": "", 'PORT': '18088', 'APP_ORIGINS': 'http://127.0.0.1:18088,http://localhost:18088',
        'APP_IMAGE': os.environ.get('ACCEPTANCE_APP_IMAGE', 'bilingual-personal-pdf-app:acceptance-candidate'),
        'PARSER_IMAGE': os.environ.get('ACCEPTANCE_PARSER_IMAGE', 'bilingual-personal-pdf-parser:acceptance-candidate')}
    commands = []
    def call(*arguments):
        argv = ['docker', 'compose', '-f', 'compose.example.yaml', '-f', str(override), '-p', project, *arguments]
        return run_recorded_command(argv, env=env, commands=commands, evidence_path=output / 'commands.json')
    try:
        call('up', '-d', '--wait', '--no-build', '--pull', 'never')
        call('run', '--rm', '--no-deps', 'maintenance', 'python', '-m', 'packages.maintenance', 'set-budget', '--budget-micro', str(approval['total_budget_micro']))
        call('run', '--rm', '--no-deps', 'maintenance', 'python', '-m', 'packages.maintenance', 'enable-dispatch')
        call('exec', '-T', 'app', 'python', '/harness/live_provider_product.py')
        receipt.write_text(json.dumps({'status': 'executed_requires_independent_review', 'project': project, 'evidence': str(output), **public}, indent=2))
        print(json.dumps({'status': 'executed_requires_independent_review', 'project': project, 'evidence': str(output)}))
    finally:
        # Preserve paid attempt/unknown-risk state and volumes. No automatic rerun.
        call('down', '--remove-orphans')


if __name__ == '__main__':
    main()
