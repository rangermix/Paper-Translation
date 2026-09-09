"""Runs only inside the separately authorized Compose instance, never ordinary pytest."""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import hashlib
import json
from pathlib import Path
import time
import uuid

from sqlalchemy import select
from packages.billing.ledger import budget_totals
from packages.domain.config import Config, provider_profile
from packages.domain.db import Database
from packages.domain.models import Attempt, Permit
from smoke_library import request, upload, etag

BASE = 'http://127.0.0.1:8080'
OUTPUT = Path('/live-evidence')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def post(path, body, tag=None, expected=202):
    headers = {'Idempotency-Key': uuid.uuid4().hex}
    if tag:
        headers['If-Match'] = tag
    return request(BASE, 'POST', path, body, headers, expected)


def wait_job(job_id):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        job, headers = request(BASE, 'GET', '/api/v1/jobs/' + job_id)
        # Preserve every observed state, including partial/unknown paid outcomes.
        (OUTPUT / ('job-' + job_id + '.json')).write_text(json.dumps(job, ensure_ascii=False, indent=2))
        if job['status'] in ('succeeded', 'ready', 'needs_review'):
            return job
        need(job['status'] not in ('outcome_unknown', 'failed', 'cancelled', 'waiting_budget', 'waiting_config'), 'Stopped without retry: ' + job['status'])
        time.sleep(.5)
    raise TimeoutError('Live job deadline reached; inspect retained attempts before retry.')


def main():
    scope = json.loads((OUTPUT / 'authorization-scope.json').read_text())
    manifest_bytes = Path('/controlled/manifest.json').read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != scope['manifest_sha256']:
        raise ValueError('Approved source manifest changed before external dispatch.')
    if hashlib.sha256(Path('/config/provider-profile.json').read_bytes()).hexdigest() != scope['profile_sha256']:
        raise ValueError('Approved Provider profile changed before external dispatch.')
    manifest = json.loads(manifest_bytes)
    profile = provider_profile()
    from packages.ir import digest
    need(profile['model_id'] == scope['model_id'] and profile['profile_revision'] == scope['profile_revision'], 'Provider identity changed.')
    server_profile, _ = request(BASE, 'GET', '/api/v1/settings/provider')
    need(server_profile.get('profile_hash') == digest(profile), 'Server public profile differs from the approved metadata.')
    approved_profile_hash = server_profile['profile_hash']
    budget = scope['total_budget_micro']
    report = {'status': 'running', 'kind': 'actual_provider_requires_independent_semantic_review', 'documents': [], 'approved_total_budget_micro': budget}
    for document in manifest['documents']:
        source_pdf = Path('/controlled') / Path(document['path']).name
        checked = upload(BASE, source_pdf.read_bytes(), document['id'] + '.pdf')
        need(checked['status'] == 'verified' and checked['sha256'] == document['sha256'], 'Controlled PDF verification failed.')
        doc, doc_headers = post('/api/v1/imports', {'source': {'kind': 'pdf_upload', 'upload_id': checked['id']},
            'source_language': document['source_language'], 'target_language': document['target_language']}, expected=201)
        parsed, _ = post('/api/v1/documents/' + doc['id'] + '/parse', {'source_asset_id': doc['source_asset_id']}, etag(doc_headers))
        parse_job = wait_job(parsed['job_id'])
        preflight, preflight_headers = request(BASE, 'GET', '/api/v1/imports/' + parse_job['import_id'] + '/preflight')
        need(preflight['can_translate'] and not preflight['unresolved'], 'Controlled source coverage is unresolved.')
        need([block['normalized_text'] for block in preflight['blocks']] == document['source_text'], 'Parsed content differs from approved exact text.')
        need(len(preflight['blocks']) == 4, 'Unexpected source block count.')
        need(preflight.get('profile_hash') == approved_profile_hash, 'Server preflight profile changed before confirmation.')
        started, _ = post('/api/v1/imports/' + preflight['id'] + '/confirm', {'source_hash': preflight['source_hash'],
            'preflight_generation': preflight['generation'], 'profile_revision': profile['profile_revision'], 'profile_hash': approved_profile_hash,
            'source_language': document['source_language'], 'locale': document['target_language'], 'budget_micro': budget,
            'external_processing_confirmed': True, 'publish_policy': 'manual_approval'}, etag(preflight_headers))
        translated = wait_job(started['job_id'])
        draft_id = translated['draft_id']
        draft, draft_headers = request(BASE, 'GET', '/api/v1/drafts/' + draft_id)
        need(all(segment['version'] > 0 for segment in draft['segments'] if segment['translatable']), 'Translation incomplete.')
        (OUTPUT / (document['id'] + '-draft.json')).write_text(json.dumps(draft, ensure_ascii=False, indent=2))
        source_term, target_term = ('tokens', '词元') if document['source_language'] == 'en' else ('token', 'tokens')
        post('/api/v1/glossaries/revisions', {'scope': 'document', 'document_id': doc['id'],
            'source_language': document['source_language'], 'target_language': document['target_language'],
            'entries': [{'source': source_term, 'target': target_term, 'mode': 'preferred', 'variants': []}]}, expected=201)
        glossary, _ = request(BASE, 'GET', '/api/v1/glossaries/effective?document_id=' + doc['id'] + '&source_language=' + document['source_language'] + '&target_language=' + document['target_language'])
        base = {'profile_revision': profile['profile_revision'], 'profile_hash': approved_profile_hash, 'glossary_revision': glossary['revision'],
            'budget_micro': budget, 'external_processing_confirmed': True}
        candidate, _ = post('/api/v1/drafts/' + draft_id + '/candidates', {**base, 'block_ids': [preflight['blocks'][1]['id']]}, etag(draft_headers))
        candidate_job = wait_job(candidate['job_id'])
        current, current_headers = request(BASE, 'GET', '/api/v1/drafts/' + draft_id)
        need([row['target_inline'] for row in current['segments']] == [row['target_inline'] for row in draft['segments']], 'Candidate unexpectedly changed current targets.')
        semantic, _ = post('/api/v1/drafts/' + draft_id + '/semantic-review', {**base, 'glossary_revision': current['glossary_revision'],
            'block_ids': [block['id'] for block in preflight['blocks']]}, etag(current_headers))
        semantic_job = wait_job(semantic['job_id'])
        need(semantic_job['progress'].get('review_completed') is True, 'Optional review did not complete.')
        report['documents'].append({'source_id': document['id'], 'document_id': doc['id'], 'draft_id': draft_id,
            'translation_job': translated['id'], 'candidate_job': candidate_job['id'], 'semantic_job': semantic_job['id'],
            'candidate_id': candidate['id'], 'external_source_blocks': 4})
        (OUTPUT / 'result.json').write_text(json.dumps(report, indent=2))
    db = Database(Config.load())
    with db.transaction() as session:
        costs = budget_totals(session)
        permits = list(session.scalars(select(Permit)))
        need(sum(costs.values()) <= budget and permits and all(permit.state == 'settled' for permit in permits), 'Unsettled risk or budget overflow remains.')
        attempts = [{'id': a.id, 'request_id': a.request_id, 'usage': a.usage, 'state': a.state} for a in session.scalars(select(Attempt)) if a.request_id]
        need(attempts and all(a['usage'] for a in attempts), 'Real Provider usage evidence is missing.')
    report.update(status='executed_requires_independent_review', costs=costs, attempts=attempts,
        publication_performed=False, human_review_created=False)
    (OUTPUT / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'status': report['status'], 'costs': costs, 'settled_requests': len(attempts)}))


if __name__ == '__main__':
    main()
