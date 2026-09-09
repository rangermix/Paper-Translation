from collections import Counter
import copy
import re

from sqlalchemy import select

from packages.domain.db import get_document, get_entity
from packages.domain.errors import require
from packages.domain.models import (Draft, Edition, IssueResolution, Job, QA, ReviewRecord,
    SegmentVersion, SourceRevision, Task, TranslationRevision, new_id, now)
from packages.ir import canonical_bytes, digest, flatten_inline, validate_ir
from packages.publisher.renderer import CSS_HASH, RENDERER_VERSION
from packages.storage import read_snapshot, write_snapshot
from packages.editorial.numbers import compare_numbers


RULE_VERSION = 'quality-v4-nonblocking'
QUALITY_MESSAGES = {
    'MISSING_TRANSLATION': '此段暂无译文，保留原文供阅读。',
    'TARGET_UNAVAILABLE': '此段译文无法安全展示，已保留原文。',
    'NUMBER_MISMATCH': '译文中的数字与原文存在差异，可查看原 PDF 对照。',
    'PROTECTED_MISMATCH': '公式、数字或引用的识别结果存在差异。',
    'SEMANTIC_RISK': '此段包含条件、否定或数量关系，可按需对照原文。',
    'TERM_REQUIRED': '此段用词与术语表不一致。', 'TERM_PREFERRED': '可考虑使用术语表中的推荐用词。',
    'TERM_FORBIDDEN': '此段出现术语表中不建议使用的词。',
    'IR_INTEGRITY': '部分内容无法按原结构展示，生成时将使用安全替代内容。',
    'OPTIONAL_REVIEW_INCOMPLETE': '辅助语义检查尚未完成，已有译文可继续使用。',
    'CHECK_FAILED': '检查未完成，已有内容仍可阅读和导出。',
    'IMAGE_UNAVAILABLE': '原图资源暂不可用，可打开原 PDF 对照。',
}


def context_hash(source, block_id):
    blocks = source['blocks']
    index = next(i for i, b in enumerate(blocks) if b['id'] == block_id)
    block = blocks[index]
    return digest({'parent': next((b['normalized_text'] for b in blocks if b['id'] == block.get('parent_id')), ''),
        'before': [b['source_hash'] for b in blocks[max(0, index-1):index]],
        'after': [b['source_hash'] for b in blocks[index+1:index+2]]})


def current_segments(session, draft_id):
    rows = session.scalars(select(SegmentVersion).where(SegmentVersion.draft_id == draft_id).order_by(SegmentVersion.block_id, SegmentVersion.sequence.desc()))
    result = {}
    for row in rows:
        result.setdefault(row.block_id, row)
    return result


def segment_fingerprint(draft, segment):
    return digest({'source': segment.source_hash, 'context': segment.context_hash, 'target': segment.target_inline,
        'version': segment.sequence, 'glossary': segment.provenance_json.get('glossary_revision', draft.glossary_revision)})


def current_review(session, draft, segment):
    return session.scalar(select(ReviewRecord).where(ReviewRecord.draft_id == draft.id,
        ReviewRecord.block_id == segment.block_id, ReviewRecord.segment_version == segment.sequence,
        ReviewRecord.fingerprint == segment_fingerprint(draft, segment)).order_by(ReviewRecord.created_at.desc()).limit(1))


def create_draft(session, config, edition, source_revision, profile, base=None):
    draft = Draft(id=new_id('draft'), document_id=edition.document_id, edition_id=edition.id,
        source_revision_id=source_revision.id, base_revision_id=base.id if base else None,
        profile=profile, glossary_revision=profile.get('glossary_revision', 'empty-v1'))
    session.add(draft)
    session.flush()
    if base:
        require(base.edition_id == edition.id and base.source_revision_id == source_revision.id, 'REVISION_MISMATCH')
        tr = read_snapshot(config.data, base)
        for result in tr['results']:
            if result['status'] != 'translated':
                continue
            session.add(SegmentVersion(id=new_id('seg'), draft_id=draft.id, block_id=result['block_id'], sequence=1,
                target_inline=result['target_inline'], source_hash=result['source_hash'], context_hash=result['context_hash'],
                origin='revision_copy', reason='New editable draft from sealed revision', provenance_json=result['generation']))
    edition.current_draft_id = draft.id
    edition.generation += 1
    return draft


def validate_target(nodes, source, block):
    require(isinstance(nodes, list) and nodes, 'TARGET_EMPTY', status=422)
    for node in nodes:
        require(isinstance(node, dict), 'TARGET_AST_INVALID', status=422)
        if node.get('type') == 'text':
            require(set(node) == {'type', 'text'} and isinstance(node['text'], str), 'TARGET_AST_INVALID', status=422)
        elif node.get('type') == 'protected_ref':
            require(set(node) == {'type', 'ref'} and node['ref'] in source['protected_atoms'] and any(
                n.get('type') == 'protected_ref' and n['ref'] == node['ref'] for n in block['source_inline']), 'TARGET_AST_INVALID', status=422)
        elif node.get('type') == 'xref':
            require(set(node) == {'type', 'target_block_id', 'label'} and isinstance(node['label'], str) and any(
                n.get('type') == 'xref' and n['target_block_id'] == node['target_block_id'] for n in block['source_inline']), 'TARGET_AST_INVALID', status=422)
        elif node.get('type') == 'link':
            require(set(node) == {'type', 'href', 'text'} and isinstance(node['text'], str) and any(
                n.get('type') == 'link' and n['href'] == node['href'] for n in block['source_inline']), 'TARGET_AST_INVALID', status=422)
        else:
            require(False, 'TARGET_AST_INVALID', status=422)
    require(flatten_inline(nodes, source['protected_atoms']).strip(), 'TARGET_EMPTY', status=422)
    # Known atom/number differences are content findings, not publication gates.


def edit_segment(session, config, draft, block_id, nodes, base_version, reason, origin='manual_ui', provenance=None):
    source = read_snapshot(config.data, get_entity(session, SourceRevision, draft.source_revision_id))
    block = next((b for b in source['blocks'] if b['id'] == block_id), None)
    require(block is not None and block['translatable'], 'NOT_FOUND', status=404)
    previous = current_segments(session, draft.id).get(block_id)
    require(base_version == (previous.sequence if previous else 0), 'SEGMENT_CONFLICT', status=412)
    validate_target(nodes, source, block)
    lineage = {'glossary_revision': draft.glossary_revision, 'glossary_entries': draft.profile.get('glossary_entries', [])}
    if previous:
        lineage.update({k: previous.provenance_json[k] for k in ('glossary_revision', 'glossary_entries') if k in previous.provenance_json})
    lineage.update(provenance or {})
    segment = SegmentVersion(id=new_id('seg'), draft_id=draft.id, block_id=block_id,
        sequence=base_version + 1, target_inline=copy.deepcopy(nodes), origin=origin, reason=reason,
        source_hash=block['source_hash'], context_hash=context_hash(source, block_id), provenance_json=lineage)
    session.add(segment)
    draft.generation += 1
    draft.qa_id = None
    session.flush()
    return segment


def translation_snapshot(session, config, draft, *, revision_id=None, draft_mode=False):
    source = read_snapshot(config.data, get_entity(session, SourceRevision, draft.source_revision_id))
    segments = current_segments(session, draft.id)
    results = []
    profile = draft.profile
    edition = session.get(Edition, draft.edition_id)
    quality = session.get(QA, draft.qa_id) if draft.qa_id else None
    quality_notes = {}
    if quality and quality.draft_generation == draft.generation:
        for finding in quality.issues:
            resolution = session.scalar(select(IssueResolution).where(IssueResolution.draft_id == draft.id,
                IssueResolution.issue_fingerprint == finding['fingerprint'])) if finding.get('resolved') else None
            note = finding.get('message') or QUALITY_MESSAGES.get(finding['code'], '此段有内容差异，可按需对照原文。')
            note += ' 已记录核对说明：' + resolution.reason if resolution else ''
            quality_notes.setdefault(finding.get('block_id') or source['title_block_id'], []).append(note)
    for block in source['blocks']:
        segment = segments.get(block['id'])
        if segment:
            try:
                require(segment.source_hash == block['source_hash'], 'SOURCE_STALE')
                validate_target(segment.target_inline, source, block)
            except (ValueError, DomainError, KeyError):
                segment = None  # Keep bad history; publish a supported original-text fallback.
        same_language = block.get('language', source['language']) == edition.target_locale
        retained = not block['translatable'] or same_language
        origin = 'retained' if retained else ('model' if segment and segment.origin in ('model', 'candidate_accepted') else 'human')
        if segment and not retained and segment.origin == 'cache':
            origin = 'cache'
        if segment and not retained and segment.origin == 'revision_copy':
            origin = segment.provenance_json.get('kind', 'human')
        review = current_review(session, draft, segment) if segment else None
        segment_profile = segment.provenance_json.get('profile', profile) if segment else profile
        if segment and segment.origin == 'revision_copy':
            p = segment.provenance_json
            segment_profile = {'provider': p.get('provider', 'none'), 'model_id': p.get('model', 'none'),
                'profile_revision': p.get('profile_version', 'manual-v1'), 'prompt_version': p.get('prompt_version', 'translate-v1')}
        glossary_revision = segment.provenance_json.get('glossary_revision', draft.glossary_revision) if segment else draft.glossary_revision
        generation = {'kind': origin, 'provider': segment_profile.get('provider', 'none'), 'model': segment_profile.get('model_id', 'none'),
            'profile_version': segment_profile.get('profile_revision', 'manual-v1'), 'prompt_version': segment_profile.get('prompt_version', 'translate-v1'),
            'glossary_revision': glossary_revision, 'attempt_id': segment.provenance_json.get('attempt_id') if segment else None}
        results.append({'block_id': block['id'], 'source_hash': block['source_hash'],
            'context_hash': context_hash(source, block['id']), 'status': 'retained' if retained else ('translated' if segment else 'unresolved'),
            'target_inline': segment.target_inline if segment and not retained else [], 'warnings': quality_notes.get(block['id'], []),
            'review_state': 'human_reviewed' if review else 'not_reviewed',
            'reason': ('same_language' if same_language and block['translatable'] else {'code':'original_code', 'math':'original_math', 'figure':'original_figure', 'table':'structural_container', 'table_cell':'empty_table_cell', 'reference':'original_reference'}.get(block['kind'], '')) if retained else '',
            'generation': generation, 'review_record': None})
        if not retained and segment is None:
            results[-1].update(status='fallback', reason='translation_unavailable',
                fallback={'mode': 'source_text' if block['normalized_text'] or not block['provenance'] else 'source_page'},
                warnings=[*results[-1]['warnings'], '此段未得到可靠译文，保留原文或原图。'])
        if review:
            # The IR schema uses an explicit content-bound review record, built from UI history only.
            results[-1]['review_record'] = {'origin': 'manual_ui', 'reviewed_at': review.created_at.isoformat(),
                'source_hash': block['source_hash'], 'target_hash': digest(segment.target_inline),
                'context_hash': context_hash(source, block['id']), 'glossary_revision': glossary_revision,
                'inherited_from': None}
    title_result = next(r for r in results if r['block_id'] == source['title_block_id'])
    title = flatten_inline(title_result['target_inline'], source['protected_atoms'])
    if title_result['reason'] == 'same_language' or title_result['status'] == 'fallback':
        title = next(b['normalized_text'] for b in source['blocks'] if b['id'] == source['title_block_id'])
    return {'id': revision_id or new_id('tr'), 'source_revision_id': source['id'], 'target_language': edition.target_locale,
        'content_policy': 'nonblocking-v1',
        'title': title, 'profile_version': profile.get('profile_revision', 'manual-v1'), 'glossary_revision': draft.glossary_revision,
        'engine': {'kind': 'model' if profile.get('provider') else 'human', 'provider': profile.get('provider', 'none'),
            'model': profile.get('model_id', 'none'), 'prompt_version': profile.get('prompt_version', 'translate-v1')},
        'sealed_at': now().isoformat(), 'results': results}


def render_input(session, source, translation, template_id='reader-v1', mode='release'):
    from packages.templates.registry import get_template
    template = get_template(template_id)
    # Publication titles are source facts, independent of mutable catalog metadata.
    block = next(b for b in source['blocks'] if b['id'] == source['title_block_id'])
    return {'schema_version': '3.0', 'document': {'id': session, 'title': block['normalized_text'],
        'notice': '来源为保存的原始 PDF。机器检查不等同于人工确认；公式和代码按声明保留。'},
        'source_revision': source, 'translation_revision': translation,
        'render': {'template_id': template_id, 'template_sha256': template['css_sha256'], 'renderer_version': template['renderer_version'],
            'settings_hash': digest({'template': template_id, 'version': template['version'], 'css_sha256': template['css_sha256'], 'js_sha256': template['js_sha256']}), 'mode': mode}}


def semantic_evidence(session, draft, source, segments):
    evidence = []
    jobs = session.scalars(select(Job).where(Job.document_id == draft.document_id, Job.stage == 'semantic_review',
        Job.payload['draft_id'].astext == draft.id).order_by(Job.created_at, Job.id))
    for job in jobs:
        if job.payload.get('source_hash') != digest(source):
            continue
        review_tasks = [task for task in session.scalars(select(Task).where(Task.job_id == job.id))
            if 'unit' in task.payload]
        # An empty findings list still reviews exact target text. Keep its
        # historical completion, but never reuse that verdict after text or
        # terminology changes, including a response that arrived already stale.
        stale = False
        for task in review_tasks:
            unit = task.payload['unit']
            segment = segments.get(unit['owner_block_id'])
            if (segment is None or digest(segment.target_inline) != unit.get('review_target_hash')
                    or segment.provenance_json.get('glossary_revision', draft.glossary_revision) != unit.get('review_glossary_revision')
                    or (task.result or {}).get('stale')):
                stale = True
        completed = (bool(job.progress.get('review_completed')) and bool(review_tasks) and not stale
            and all(task.status == 'succeeded' for task in review_tasks))
        findings = []
        for finding in job.progress.get('semantic_issues', []):
            segment = segments.get(finding.get('block_id'))
            if (segment and not finding.get('stale') and finding.get('target_hash') == digest(segment.target_inline)
                    and finding.get('glossary_revision') == segment.provenance_json.get('glossary_revision', draft.glossary_revision)):
                findings.append(finding)
        evidence.append({'job_id': job.id, 'status': 'stale' if stale else job.status, 'completed': completed,
            'block_ids': job.payload.get('block_ids', []), 'findings': findings})
    return evidence


def quality_fingerprint(draft, source, segments, semantic):
    return digest({'source': digest(source), 'draft_generation': draft.generation,
        'targets': {bid: {'inline': s.target_inline, 'lineage': s.provenance_json} for bid, s in segments.items()},
        'glossary': draft.glossary_revision, 'profile': draft.profile, 'rules': RULE_VERSION, 'semantic': semantic})


def _run_quality(session, config, draft):
    source = read_snapshot(config.data, get_entity(session, SourceRevision, draft.source_revision_id))
    segments = current_segments(session, draft.id)
    semantic = semantic_evidence(session, draft, source, segments)
    fingerprint = quality_fingerprint(draft, source, segments, semantic)
    edition = session.get(Edition, draft.edition_id)
    issues = []
    def issue(code, block_id, severity, evidence):
        item = {'code': code, 'block_id': block_id, 'severity': 'important' if severity in {'hard', 'high'} else 'general',
            'blocking': False, 'rule_version': RULE_VERSION, 'evidence': evidence}
        item['fingerprint'] = digest({'issue': item, 'source': digest(source),
            'target': segments[block_id].target_inline if block_id in segments else None, 'glossary': draft.glossary_revision})
        block = next((b for b in source['blocks'] if b['id'] == block_id), None)
        item.update(id=item['fingerprint'], stage='translation', block_ids=[block_id] if block_id else [],
            page=block['provenance'][0]['page'] if block and block['provenance'] else None,
            category='numeric' if code == 'NUMBER_MISMATCH' else 'coverage' if code in {'MISSING_TRANSLATION','TARGET_UNAVAILABLE'} else 'terminology' if code.startswith('TERM_') else 'semantic',
            message=QUALITY_MESSAGES.get(code, '此段有内容差异，可按需对照原文。'), evidence_refs=[item['fingerprint']], diagnostic_count=1)
        resolved = session.scalar(select(IssueResolution).where(IssueResolution.draft_id == draft.id, IssueResolution.issue_fingerprint == item['fingerprint']))
        item['resolved'] = bool(resolved)
        issues.append(item)
    for block in source['blocks']:
        if not block['translatable'] or block.get('language', source['language']) == edition.target_locale:
            continue
        segment = segments.get(block['id'])
        if not segment:
            issue('MISSING_TRANSLATION', block['id'], 'hard', {})
            continue
        try:
            require(segment.source_hash == block['source_hash'], 'SOURCE_STALE')
            validate_target(segment.target_inline, source, block)
        except (ValueError, DomainError, KeyError):
            issue('TARGET_UNAVAILABLE', block['id'], 'hard', {'fallback': 'source_text'})
            continue
        src, target = block['normalized_text'], flatten_inline(segment.target_inline, source['protected_atoms'])
        src_refs = Counter(n['ref'] for n in block['source_inline'] if n['type'] == 'protected_ref')
        trg_refs = Counter(n['ref'] for n in segment.target_inline if n['type'] == 'protected_ref')
        if src_refs != trg_refs:
            issue('PROTECTED_MISMATCH', block['id'], 'hard', {'source': dict(src_refs), 'target': dict(trg_refs)})
        numbers = compare_numbers(src, target)
        if not numbers['matches']:
            issue('NUMBER_MISMATCH', block['id'], 'hard', {'source': src, 'target': target, **numbers})
        if re.search(r'\b(not|never|unless|only|without|less|greater|must|cannot|except)\b|不|仅|除非|只有|未', src, flags=re.I):
            if not current_review(session, draft, segment):
                issue('SEMANTIC_RISK', block['id'], 'high', {'source': src, 'target': target, 'note': 'Compare negation, conditions and quantitative relationships against the PDF.'})
        if not target.strip():
            issue('EMPTY_TRANSLATION', block['id'], 'hard', {})
        from packages.glossaries import term_matches
        for term in segment.provenance_json.get('glossary_entries', draft.profile.get('glossary_entries', [])):
            if not term_matches(src, term):
                continue
            allowed = [term['source'] if term['mode'] == 'retain' else term['target'], *term.get('variants', [])]
            present = any(word and word in target for word in allowed)
            if term['mode'] == 'forbidden' and term['target'] in target:
                issue('TERM_FORBIDDEN', block['id'], 'high', {'term': term, 'source': src, 'target': target})
            elif term['mode'] in ('must', 'retain') and not present:
                issue('TERM_REQUIRED', block['id'], 'high', {'term': term, 'source': src, 'target': target})
            elif term['mode'] == 'preferred' and not present:
                issue('TERM_PREFERRED', block['id'], 'warning', {'term': term, 'source': src, 'target': target})
    for asset in source['assets']:
        if asset['media_type'].startswith('image/') and not (config.data / asset['storage_key']).is_file():
            owners = [block['id'] for block in source['blocks'] if asset['id'] in {
                block.get('attributes', {}).get('asset_id'), block.get('attributes', {}).get('comparison_asset_id')}]
            for owner in owners or ['']:
                issue('IMAGE_UNAVAILABLE', owner, 'warning', {'asset_id': asset['id'], 'fallback': 'original_pdf'})
    # Optional model review remains issue-only. Only exact current source and target
    # evidence can affect this QA; a model score can never create a review record.
    for semantic_job in semantic:
        if not semantic_job['completed']:
            issue('OPTIONAL_REVIEW_INCOMPLETE', '', 'warning', {'job_id': semantic_job['job_id'], 'status': semantic_job['status'],
                'note': 'Optional semantic review has not completed. No semantic accuracy certification is implied.'})
        for finding in semantic_job['findings']:
            issue('SEMANTIC_' + finding.get('rule', 'RISK').upper(), finding['block_id'],
                'high' if finding.get('severity') in ('high', 'critical', 'error') else 'warning', finding)
    try:
        tr = translation_snapshot(session, config, draft)
        validate_ir(render_input(draft.document_id, source, tr), config.data)
    except (ValueError, DomainError) as exc:
        issue('IR_INTEGRITY', '', 'hard', {'message': str(exc)[:500]})
    # Content review is optional. Keep semantic/terminology findings and their
    # unresolved status in the publication, without manufacturing human approval.
    # Valid describes this diagnostic summary; it is never an execution gate.
    qa = QA(id=new_id('qa'), draft_id=draft.id, draft_generation=draft.generation,
        fingerprint=fingerprint, issues=issues, valid=not any(i['severity'] == 'important' for i in issues))
    session.add(qa)
    draft.qa_id = qa.id
    session.flush()
    return qa


def quality_summary(qa):
    from packages.domain.workflow import QualitySummary
    counts = {level: sum(i.get('severity') == level for i in qa.issues) for level in ('important', 'general', 'info')}
    return QualitySummary(state='failed' if any(i['code'] == 'CHECK_FAILED' for i in qa.issues) else 'completed',
        diagnostic_count=len(qa.issues), **counts).model_dump()


def run_quality(session, config, draft, *, parent_job_id=None):
    """A failed content checker records its actual result and leaves safe sealing available."""
    from packages.domain.models import Attempt
    receipt = Job(id=new_id('job'), document_id=draft.document_id, parent_job_id=parent_job_id,
        stage='quality_check', status='running', payload={'draft_id': draft.id}, actual_model={'kind': 'none', 'models': []})
    session.add(receipt); session.flush()
    task = Task(id=new_id('task'), job_id=receipt.id, kind='quality_check', status='leased', fence=1, attempts=1,
        actual_model=receipt.actual_model)
    session.add(task); session.flush()
    attempt = Attempt(id=new_id('attempt'), job_id=receipt.id, task_id=task.id, fence=1, control_epoch=0,
        actual_model=receipt.actual_model)
    session.add(attempt); session.flush()
    try:
        with session.begin_nested():
            qa = _run_quality(session, config, draft)
    except (ValueError, RuntimeError, KeyError, TypeError):
        source = read_snapshot(config.data, get_entity(session, SourceRevision, draft.source_revision_id))
        segments = current_segments(session, draft.id)
        fingerprint = quality_fingerprint(draft, source, segments, semantic_evidence(session, draft, source, segments))
        finding = {'code': 'CHECK_FAILED', 'block_id': '', 'severity': 'general', 'blocking': False,
            'rule_version': RULE_VERSION, 'message': '检查未完成，已有内容仍可阅读和导出。', 'evidence': {},
            'fingerprint': digest({'check_failed': fingerprint}), 'resolved': False}
        qa = QA(id=new_id('qa'), draft_id=draft.id, draft_generation=draft.generation,
            fingerprint=fingerprint, issues=[finding], valid=False)
        session.add(qa); draft.qa_id = qa.id
    receipt.quality_summary = quality_summary(qa)
    failed = receipt.quality_summary['state'] == 'failed'
    receipt.status = task.status = attempt.state = 'failed' if failed else 'succeeded'
    receipt.error = {'code': 'CHECK_FAILED'} if failed else None
    receipt.progress = {'qa_id': qa.id, 'issues': len(qa.issues)}
    task.result = {'qa_id': qa.id}
    session.flush()
    return qa


def seal(session, config, draft, qa_id=None, qa_fingerprint=None):
    qa = session.get(QA, qa_id) if qa_id else None
    source = read_snapshot(config.data, get_entity(session, SourceRevision, draft.source_revision_id))
    segments = current_segments(session, draft.id)
    current_fingerprint = quality_fingerprint(draft, source, segments, semantic_evidence(session, draft, source, segments))
    if not (qa and qa.draft_id == draft.id and qa.id == draft.qa_id and qa.draft_generation == draft.generation
            and qa.fingerprint == qa_fingerprint == current_fingerprint):
        qa = run_quality(session, config, draft)
    revision_id = new_id('tr')
    tr = translation_snapshot(session, config, draft, revision_id=revision_id)
    source = read_snapshot(config.data, get_entity(session, SourceRevision, draft.source_revision_id))
    try:
        validate_ir(render_input(draft.document_id, source, tr), config.data)
    except ValueError:
        require(False, 'PUBLICATION_INPUT_INVALID')
    key = f'documents/{draft.document_id}/translations/{tr["target_language"]}/{revision_id}.json'
    h = write_snapshot(config.data, key, tr)
    revision = TranslationRevision(id=revision_id, document_id=draft.document_id, edition_id=draft.edition_id,
        source_revision_id=draft.source_revision_id, parent_id=draft.base_revision_id,
        snapshot_hash=h, storage_key=key, qa_fingerprint=qa.fingerprint)
    session.add(revision)
    session.flush()
    return revision


from packages.domain.errors import DomainError
