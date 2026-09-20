"""Conservative original-only policy over source facts; never rewrites the IR.

Keep this v1 policy stable: sealed translations record its retention reasons.
Uncertain text remains eligible for translation, particularly outside front matter.
"""
import re
import unicodedata


POLICY_VERSION = 'academic-original-only-v1'
REFERENCE_HEADINGS = {
    'references', 'bibliography', 'works cited', 'literature cited', 'references cited',
    'reference list', 'bibliographic references', 'selected bibliography',
    '参考文献', '參考文獻', '参考文献一覧', '引用文献', '참고문헌',
    'références', 'références bibliographiques', 'bibliographie',
    'literaturverzeichnis', 'literatur', 'bibliografía', 'bibliografia',
    'referencias', 'referencias bibliográficas', 'referências', 'referências bibliográficas',
}
TEXT_KINDS = {'paragraph', 'list_item', 'footnote'}
PROSE_HEADINGS = {'abstract', 'summary', 'introduction', 'conclusion', 'conclusions',
    'author contributions', 'author contribution', 'acknowledgments', 'acknowledgements',
    'funding', 'funding statement', 'data availability', 'data availability statement',
    'conflict of interest', 'conflicts of interest', 'competing interests',
    'supplementary material', 'supplementary materials', 'supporting information',
    '作者贡献', '作者貢獻', '致谢', '致謝', '利益冲突', '利益衝突'}
_AUTHOR_LABEL = re.compile(r'^(?:authors?|作者)\s*[:：]\s*', re.I)
_EMAIL = re.compile(r'(?:mailto:)?[\w.!#$%&\'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+', re.I)
_ORGANISATION = re.compile(
    r'\b(?:universit[yaéät]+|universidad|universidade|institute|institut|department|'
    r'school|college|laborator(?:y|ies)|academy|hospital|research (?:centre|center))\b'
    r'|大学|大學|学院|學院|研究所|研究院|研究室|实验室|實驗室', re.I)
_PROSE = re.compile(
    r'\b(?:we|our|this|these|those|which|who|thank|thanks|propose|proposes|evaluate|'
    r'evaluated|evaluates|show|shows|demonstrate|demonstrates|compare|compares|'
    r'found|used|uses|using|written|includes|include|is|are|was|were|has|have)\b'
    r'|我们|我們|本文|本研究|提出|证明|證明|感谢|感謝', re.I)
_BODY_LABEL = re.compile(r'(?:^|\n)\s*(?:abstract|summary|keywords?|introduction|acknowledg(?:e)?ments|摘要|关键词|關鍵詞)\b', re.I)
_CONNECTORS = {'of', 'the', 'for', 'and', 'in', 'at', 'de', 'des', 'del', 'der', 'für', 'y', 'et', 'du', 'la', 'di', 'da', 'do', 'dos', 'und'}
_COMPANY = re.compile(r'\b(?:research|labs?|ai|deepmind|openai|inc|ltd|llc|corp)\b', re.I)
_TEX_AFFILIATION_MARKER = re.compile(
    r'\$\s*\^\s*\{(?:\\(?:dagger|ddagger|ast|star)\b|[\d\s,*†‡§¶✉])+\}\s*\$')


def _text(block):
    return unicodedata.normalize('NFKC', block.get('normalized_text', '')).strip()


def _heading_label(text):
    label = re.sub(r'^(?:\d+(?:\.\d+)*|[IVXLCDM]+)[.)]?\s+', '', text, flags=re.I)
    return ' '.join(label.strip(' .:：').casefold().split())


def _prose_heading(text):
    label = _heading_label(text)
    return label in PROSE_HEADINGS or bool(re.match(r'^(?:appendix|appendices)\b|^(?:附录|附錄)', label))


def _identifier_reason(text):
    # Metadata lines are short. Bound regex work before scanning long prose or
    # malformed addresses; in particular never search for email without an @.
    if len(text) > 1000:
        return None
    if re.fullmatch(r'(?:doi\s*:\s*)?10\.\d{4,9}/\S+', text, re.I):
        return 'original_identifier'
    if re.fullmatch(r'(?:https?://\S+|(?:orcid\s*:\s*)?\d{4}-\d{4}-\d{4}-\d{3}[\dX])', text, re.I):
        return 'original_identifier'
    if '@' not in text:
        return None
    label_free = re.sub(r'^(?:e-?mails?|corresponding authors?|correspondence|电子邮箱|電子郵箱)\s*[:：]\s*', '', text, flags=re.I)
    remainder, count = _EMAIL.subn('', label_free)
    if count and not remainder.strip(' ,;，；<>[](){}*†‡\n\t'):
        return 'original_contact'
    return None


def _affiliation(text, *, after_author=False):
    if len(text) > 500:
        return False
    text = _TEX_AFFILIATION_MARKER.sub(' ', text)
    if _PROSE.search(text) or _BODY_LABEL.search(text) or re.search('[。！？]', text):
        return False
    if re.match(r'^(?:affiliations?|institutions?|organizations?|organisations?|作者单位|作者單位)\s*[:：]\s*\S', text, re.I):
        return True
    if not (_ORGANISATION.search(text) or after_author and _COMPANY.search(text)):
        return False
    # An organisation keyword inside an ordinary sentence is not affiliation
    # evidence. Require a name/address-shaped line, including uncased scripts.
    words = re.findall(r'[^\W\d_]+', text)
    return bool(words) and all(w[0].isupper() or w.lower() == w.upper() or w in _CONNECTORS for w in words)


def _name_count(text):
    """Names alone need either a list or neighbouring affiliation evidence."""
    if not text or len(text) > 1000 or _PROSE.search(text) or _BODY_LABEL.search(text) or _affiliation(text):
        return 0
    explicit = bool(_AUTHOR_LABEL.match(text))
    text = _AUTHOR_LABEL.sub('', text)
    # Superscript affiliation markers also delimit names in a typeset byline.
    # Restrict this to marker syntax; ordinary mathematical text is not a name.
    text = _TEX_AFFILIATION_MARKER.sub(';', text)
    text = re.sub(r'\d+(?:\s*,\s*\d+)*|[*†‡§¶✉]', '', text)
    names = [part.strip() for part in re.split(r'\s+(?:and|und|et|y)\s+|[,;，；、&\n]', text) if part.strip()]
    for name in names:
        if re.fullmatch(r'[\u3400-\u9fff]{2,4}', name):
            continue
        words = name.split()
        if not 2 <= len(words) <= 5:
            return 0
        for word in words:
            letters = word.replace('.', '').replace('-', '').replace("'", '').replace('’', '')
            if not letters.isalpha() or not (explicit or letters[0].isupper() or word in {'de', 'del', 'van', 'von', 'der', 'da', 'dos', 'di', 'la'}):
                return 0
    return max(len(names), 2) if explicit and names else len(names)


def _alphanumeric_identifier(text):
    return (len(text) <= 80 and re.search(r'\d', text)
        and re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*', text))


def _table_cell_reason(block, text, atoms):
    if re.search(r'\d', text) and (re.fullmatch(r'[\d\s.,+−\-±%‰()/×÷<>≤≥=]+(?:[eE][+\-]?\d+)?', text)
            or re.fullmatch(r'\d+\s*\([A-Z]\)', text)):
        return 'original_numeric_cell'
    nodes = block.get('source_inline', [])
    if (any(node['type'] == 'protected_ref' for node in nodes)
            and all(node['type'] == 'text' and not node['text'].strip()
                or node['type'] == 'protected_ref' and atoms.get(node['ref'], {}).get('kind') == 'math'
                for node in nodes)):
        return 'original_math_cell'
    # Single alphanumeric identifiers such as VGG16 and Inception-v3 carry no
    # translatable prose. Whitespace, units and descriptions remain eligible.
    if _alphanumeric_identifier(text):
        return 'original_identifier_cell'
    return None


def original_only_blocks(source):
    """Return detected block IDs and exact retention reasons in reading order.

    References use section boundaries; bylines and affiliations use the contiguous
    front matter after the title on its page. Pure contact/identifier lines need
    no positional inference. Isolated identifier captions stay original; titles,
    prose captions and ordinary footnotes remain eligible for translation.
    """
    blocks = sorted(source.get('blocks', []), key=lambda b: b['order'])
    title_id = source.get('title_block_id')
    title = next((b for b in blocks if b['id'] == title_id), {})
    title_pages = {loc['page'] for loc in title.get('provenance', [])}
    reasons = {}
    bibliography = False
    front = False
    after_author = False
    for index, block in enumerate(blocks):
        bid, kind, text = block['id'], block['kind'], _text(block)
        if bid == title_id:
            front = True
            bibliography = False
            continue
        if kind == 'caption' and _alphanumeric_identifier(re.sub(r'^\([A-Za-z]\)\s+', '', text)):
            reasons[bid] = 'original_identifier_label'
            front = False
            continue
        if kind == 'table_cell':
            cell_reason = _table_cell_reason(block, text, source.get('protected_atoms', {}))
            if cell_reason:
                reasons[bid] = cell_reason
                continue
        root = block.get('owner_id') is None
        if root and kind in {'heading', 'paragraph'} and _heading_label(text) in REFERENCE_HEADINGS:
            reasons[bid] = 'original_bibliography_heading'
            bibliography = True
            front = False
            continue
        if root and (kind == 'heading' or kind == 'paragraph' and _prose_heading(text)):
            bibliography = False
            front = False
        if kind == 'reference' or (bibliography and kind in TEXT_KINDS | {'table_cell'}):
            reasons[bid] = 'original_reference'
            continue
        if root and kind in TEXT_KINDS:
            identifier = _identifier_reason(text)
            if identifier:
                reasons[bid] = identifier
                continue
        if not front:
            continue
        pages = {loc['page'] for loc in block.get('provenance', [])}
        if pages and title_pages and not pages <= title_pages:
            front = False
            continue
        if not root or kind not in TEXT_KINDS:
            front = False
            continue
        if not text:
            continue
        if _affiliation(text, after_author=after_author):
            reasons[bid] = 'original_affiliation'
            continue
        names = _name_count(text)
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        adjacent_metadata = (following is not None and following['kind'] in TEXT_KINDS
            and following.get('owner_id') is None and (_affiliation(_text(following), after_author=True)
                or _identifier_reason(_text(following))))
        author_markers = bool(re.search(r'[\w][\d*†‡§¶]', text) or _TEX_AFFILIATION_MARKER.search(text))
        if names and (adjacent_metadata or after_author or _AUTHOR_LABEL.match(text) or author_markers):
            reasons[bid] = 'original_author_list'
            after_author = True
        else:
            front = False
    return reasons


def metadata_literals(source, reasons=None):
    """Exact full names from confirmed metadata, longest first for inline matching.

    The optional reasons map is the caller's precomputed original_only_blocks
    result. Detection may normalize a candidate; returned literals preserve the
    persisted spelling and never alter source text, atoms, or history.
    """
    if reasons is None:
        reasons = original_only_blocks(source)
    literals = set()
    for block in source.get('blocks', []):
        reason = reasons.get(block['id'])
        if reason not in {'original_author_list', 'original_affiliation'}:
            continue
        text = block.get('normalized_text', '').strip()
        if len(text) > 1000:
            continue
        explicit_author = bool(_AUTHOR_LABEL.match(text))
        text = _TEX_AFFILIATION_MARKER.sub(';', text)
        if reason == 'original_author_list':
            text = _AUTHOR_LABEL.sub('', text)
            text = re.sub(r'\d+(?:\s*,\s*\d+)*|[*†‡§¶✉⁰¹²³⁴⁵⁶⁷⁸⁹]+', ';', text)
            parts = re.split(r'\s+(?:and|und|et|y)\s+|[,;，；、&\n]', text)
            for part in parts:
                literal = part.strip()
                candidate = unicodedata.normalize('NFKC', literal)
                if _name_count(('Authors: ' if explicit_author else '') + candidate):
                    literals.add(literal)
        else:
            text = re.sub(r'^(?:affiliations?|institutions?|organizations?|organisations?|作者单位|作者單位)\s*[:：]\s*', '', text, flags=re.I)
            text = re.sub(r'[*†‡§¶✉⁰¹²³⁴⁵⁶⁷⁸⁹]+', ';', text)
            for part in re.split(r'[,;，；\n]', text):
                literal = re.sub(r'^\d+(?:,\d+)*\s+', '', part.strip(' \t?'))
                candidate = unicodedata.normalize('NFKC', literal)
                words = re.findall(r'[^\W\d_]+', candidate)
                distinctive = any(word.casefold() not in _CONNECTORS | {'centre', 'center'}
                    and not _ORGANISATION.fullmatch(word) and not _COMPANY.fullmatch(word) for word in words)
                named = (len(words) >= 2 and distinctive or candidate.casefold() in {'openai', 'deepmind'}
                    or len(candidate) >= 4 and any(c.isalpha() and c.lower() == c.upper() for c in candidate))
                if named and _affiliation(candidate, after_author=True):
                    literals.add(literal)
    return tuple(sorted(literals, key=lambda value: (-len(value), value)))
