"""Versioned literal term matching and explicit document-over-global precedence."""
import copy
import re

from sqlalchemy import select

from packages.domain.db import get_document
from packages.domain.errors import require
from packages.domain.models import Glossary
from packages.ir import digest

MATCHER_VERSION = 'literal-word-cjk-v1'


def _key(entry):
    return entry['source'].casefold()


def validate_entries(entries):
    require(isinstance(entries, list) and len(entries) <= 10000, 'GLOSSARY_INVALID', status=422)
    normalized = []
    fields = {'source', 'target', 'mode', 'variants', 'case_sensitive', 'note'}
    for entry in entries:
        require(isinstance(entry, dict) and not set(entry) - fields, 'GLOSSARY_INVALID', status=422)
        require(isinstance(entry.get('source'), str) and 0 < len(entry['source'].strip()) <= 200, 'GLOSSARY_INVALID', status=422)
        require(isinstance(entry.get('target', ''), str) and len(entry.get('target', '')) <= 500, 'GLOSSARY_INVALID', status=422)
        require(entry.get('mode', 'preferred') in {'must', 'preferred', 'forbidden', 'retain'}, 'GLOSSARY_INVALID', status=422)
        require(entry.get('mode') == 'retain' or entry.get('target', '').strip(), 'GLOSSARY_INVALID', status=422)
        variants = entry.get('variants', [])
        require(isinstance(variants, list) and len(variants) <= 100 and all(isinstance(v, str) and len(v) <= 500 for v in variants), 'GLOSSARY_INVALID', status=422)
        require(type(entry.get('case_sensitive', False)) is bool and isinstance(entry.get('note', ''), str) and len(entry.get('note', '')) <= 2000, 'GLOSSARY_INVALID', status=422)
        normalized.append({'source': entry['source'].strip(), 'target': entry.get('target', '').strip(),
            'mode': entry.get('mode', 'preferred'), 'variants': variants, 'case_sensitive': entry.get('case_sensitive', False), 'note': entry.get('note', '')})
    return normalized


def _validate_scope(entries):
    groups = {}
    for entry in entries:
        groups.setdefault(_key(entry), []).append(entry)
    for term, group in groups.items():
        positive = {entry['source'] if entry['mode'] == 'retain' else entry['target'] for entry in group if entry['mode'] != 'forbidden'}
        forbidden = {entry['target'] for entry in group if entry['mode'] == 'forbidden'}
        require(len(positive) <= 1 and not positive.intersection(forbidden), 'GLOSSARY_CONFLICT',
            'Same-scope terminology conflict must be resolved before dispatch.', details={'source': term, 'entries': group})
    return list({digest(entry): entry for entry in entries}.values())


def merge_entries(global_entries, document_entries):
    global_entries = _validate_scope(validate_entries(global_entries))
    document_entries = _validate_scope(validate_entries(document_entries))
    overridden = {_key(entry) for entry in document_entries}
    return copy.deepcopy([entry for entry in global_entries if _key(entry) not in overridden] + document_entries)


def term_matches(text, entry):
    """User text is escaped; no regular expression input is ever executed."""
    term = entry['source']
    flags = 0 if entry.get('case_sensitive', False) else re.IGNORECASE
    has_cjk = bool(re.search(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]', term))
    prefix = r'(?<!\w)' if not has_cjk and (term[:1].isalnum() or term.startswith('_')) else ''
    suffix = r'(?!\w)' if not has_cjk and (term[-1:].isalnum() or term.endswith('_')) else ''
    return re.search(prefix + re.escape(term) + suffix, text, flags) is not None


def effective_glossary(session, doc_id, source_lang, target_locale):
    get_document(session, doc_id)
    base_query = select(Glossary).where(Glossary.source_language == source_lang, Glossary.target_language == target_locale).order_by(Glossary.created_at.desc(), Glossary.id.desc()).limit(1)
    global_revision = session.scalar(base_query.where(Glossary.document_id.is_(None)))
    document_revision = session.scalar(base_query.where(Glossary.document_id == doc_id))
    entries = merge_entries(global_revision.entries if global_revision else [], document_revision.entries if document_revision else [])
    revisions = [x.id for x in (global_revision, document_revision) if x]
    return {'revision': digest({'revisions': revisions, 'entries': entries, 'matcher': MATCHER_VERSION}) if revisions else 'empty-v1',
        'entries': entries, 'matcher_version': MATCHER_VERSION, 'source_revision_ids': revisions}


__all__ = ['effective_glossary', 'merge_entries', 'term_matches', 'validate_entries', 'MATCHER_VERSION']
