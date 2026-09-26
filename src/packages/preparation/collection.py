"""Extract exact source passages without a model, downloads or source changes."""
import re

from packages.ir import digest
from packages.ir.retention import original_only_blocks
from .terms import ACRONYM, DEFINITION, VERSION as TERM_VERSION, extract, scope_map

VERSION = 'paper-evidence-v1'
TEXT_KINDS = {'title', 'heading', 'paragraph', 'list_item', 'footnote', 'caption', 'table_cell'}
ABSTRACT = re.compile(r'^(?:\d+[. ]*)?(?:abstract|summary|摘要|概要)\b', re.I)
CONCLUSION = re.compile(r'^(?:\d+[. ]*)?(?:conclusions?|discussion|结论|結論|总结|總結)\b', re.I)
CONTRIBUTION = re.compile(r'\b(?:our (?:main )?contributions?|we (?:propose|present|introduce|demonstrate))\b|本文提出|主要贡献|主要貢獻', re.I)


def collect(source, *, max_evidence=96, max_concepts=48):
    retained = original_only_blocks(source)
    blocks = [b for b in source['blocks'] if b['id'] not in retained and b['kind'] in TEXT_KINDS]
    scopes = scope_map(source['blocks'])
    by = {b['id']: b for b in blocks}
    evidence = []
    oversized = 0
    for block in blocks:
        text = block['normalized_text']
        section = by.get(scopes[block['id']], {}).get('normalized_text', '')
        for sentence in re.split(r'(?<=[.!?])\s+|(?<=[。！？])', text):
            quote = sentence.strip()
            if not quote:
                continue
            if len(quote) > 700:
                oversized += 1
                continue
            roles = []
            if block['kind'] in {'title', 'heading'}:
                roles.append(block['kind'])
            if ABSTRACT.search(section) or ABSTRACT.search(quote):
                roles.append('abstract')
            if CONCLUSION.search(section):
                roles.append('conclusion')
            if DEFINITION.search(quote) or re.search(r'定义|定義|称为|稱為', quote):
                roles.append('definition')
            if ACRONYM.search(quote):
                roles.append('acronym')
            if CONTRIBUTION.search(quote):
                roles.append('contribution')
            if block['kind'] in {'caption', 'table_cell'}:
                roles.append(block['kind'])
            # Keep some ordinary passages for lexical evidence as capacity allows.
            for role in roles or ['passage']:
                item = {'block_id': block['id'], 'source_hash': block['source_hash'],
                        'quote': quote, 'role': role, 'scope': scopes[block['id']]}
                evidence.append({'id': 'evidence-' + digest(item)[:20], **item})
    priority = {'definition': 0, 'acronym': 1, 'abstract': 2, 'contribution': 3,
                'conclusion': 4, 'title': 5, 'heading': 6, 'caption': 7, 'table_cell': 8, 'passage': 9}
    all_evidence = sorted(evidence, key=lambda e: priority[e['role']])
    evidence = all_evidence[:max_evidence]
    stats = {}
    concepts = extract(blocks, evidence, scopes, max_concepts=max_concepts, stats=stats)
    pack = {'version': VERSION, 'term_version': TERM_VERSION, 'source_hash': digest(source),
            'source_revision_id': source['id'], 'source_language': source['language'],
            'evidence': evidence, 'concepts': concepts,
            'headings': [{'block_id': b['id'], 'text': b['normalized_text'][:200]}
                         for b in blocks if b['kind'] in {'title', 'heading'}][:80],
            'coverage': {'scanned_blocks': len(source['blocks']), 'eligible_blocks': len(blocks),
                         'omitted_evidence': oversized + max(0, len(all_evidence) - len(evidence)),
                         'oversized_passages': oversized, **stats,
                         'term_methods': ['definition', 'acronym', 'English phrase frequency'],
                         'model_saw_full_paper': False}}
    return {**pack, 'revision': digest(pack)}
