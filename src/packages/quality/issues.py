"""Stable page/region issue aggregation. Original diagnostics are never edited."""
from collections import Counter
import re

from packages.domain.workflow import ContentIssue, QualitySummary
from packages.ir import digest

RULE_VERSION = 'page-issues-v1'


def comparison_text(text, *, prose=True):
    # Avoid NFKC: it collapses exponent/subscript digits into ordinary numbers.
    text = text.translate(str.maketrans({'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl', '\u00ad': ''}))
    if prose:
        text = re.sub(r'(?<=[^\W\d_])-\s*\n\s*(?=[^\W\d_])', '', text)
        text = re.sub(r'(?<=[^\W\d_])[†‡](?=\s|$)', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _classification(row):
    if row.get('code') == 'CHECK_FAILED':
        return 'check', 'general', '检查未完成，已有内容仍可阅读'
    words = (str(row.get('reason', '')) + ' ' + str(row.get('code', ''))).lower()
    if any(term in words for term in ('footnote marker', 'soft hyphen', 'line-wrap', 'ligature')):
        return 'typography', 'info', '文字排版与原 PDF 有细微差异'
    if any(term in words for term in ('number', 'numeric', 'digit')):
        return 'number', 'important', '数字与原 PDF 可能不同'
    if 'table' in words:
        return 'table', 'important', '表格内容与原 PDF 可能不同'
    if 'formula' in words or 'math' in words:
        return 'formula', 'general', '公式保留原图对照'
    if 'code' in words and 'source_parse_review' not in words:
        return 'code', 'general', '代码保留原图对照'
    if 'duplicate' in words:
        return 'duplicate', 'general', '可能存在重复内容'
    return 'coverage', 'important', '部分内容与原 PDF 不一致'


def _near(a, b):
    if a is None or b is None:
        return a is None and b is None
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    width = max(1, min(a[2] - a[0], b[2] - b[0]))
    return overlap / width >= .6 and max(a[1], b[1]) <= min(a[3], b[3]) + 12


def aggregate_source_issues(coverage, source):
    raw = coverage.get('unresolved', [])
    represented = {loc['page'] for b in source.get('blocks', []) for loc in b.get('provenance', [])}
    groups = []
    for index, row in enumerate(raw):
        page = row.get('page', row.get('page_number'))
        page = page if type(page) is int and page >= 1 else None
        missing = page is not None and page not in represented
        category, severity, message = ('page_missing', 'important', f'第 {page} 页文字未完整提取') if missing else _classification(row)
        bounds = row.get('bbox') if not missing else None
        if not (isinstance(bounds, (list, tuple)) and len(bounds) == 4 and all(type(n) in (int, float) for n in bounds)):
            bounds = None
        block_ids = [row['block_id']] if row.get('block_id') else []
        match = next((g for g in groups if g['page'] == page and g['category'] == category and
                      (missing or (_near(g['bbox'], bounds) and (page is not None or g['block_ids'] == block_ids)))), None)
        if match is None:
            match = dict(page=page, category=category, severity=severity, message=message, bbox=bounds,
                         block_ids=block_ids, evidence_refs=[], diagnostic_count=0)
            groups.append(match)
        elif match['bbox'] and bounds:
            a = match['bbox']
            match['bbox'] = [min(a[0], bounds[0]), min(a[1], bounds[1]), max(a[2], bounds[2]), max(a[3], bounds[3])]
        match['block_ids'] = sorted(set(match['block_ids'] + block_ids))
        match['evidence_refs'].append(f'coverage.unresolved[{index}]')
        match['diagnostic_count'] += 1
    issues = []
    for group in groups:
        stable = {k: group[k] for k in ('page', 'category', 'bbox', 'block_ids')}
        issues.append(ContentIssue(id='issue-' + digest(stable)[:24], stage='source_check', **group).model_dump(mode='json'))
    counts = Counter(issue['severity'] for issue in issues)
    state = coverage.get('check_state', 'completed' if 'unresolved' in coverage else 'not_checked')
    if state not in {'not_checked', 'checking', 'completed', 'stale', 'failed'}:
        state = 'not_checked'
    quality = QualitySummary(state=state, important=counts['important'], general=counts['general'], info=counts['info'], diagnostic_count=len(raw))
    return {'issues': issues, 'quality': quality.model_dump(), 'rule_version': RULE_VERSION}
