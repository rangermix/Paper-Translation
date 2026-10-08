"""Protect printed variable labels only when adjacent code defines the name."""
import ast
import re


PARENTHESIZED_NAME = re.compile(r'\([ \t]*([A-Za-z_]\w{0,127})[ \t]*\)|（[ \t]*([A-Za-z_]\w{0,127})[ \t]*）', re.ASCII)


def _defined_names(block):
    # Python declarations provide deterministic source evidence. Unsupported
    # languages, image transcriptions and invalid snippets establish no names;
    # never execute code or infer declarations from comments/string literals.
    if block['kind'] != 'code' or block.get('translatable'):
        return set()
    language = block.get('attributes', {}).get('code_language', '').casefold()
    value = block.get('normalized_text', '')
    if language not in {'python', 'python3', 'py'} or not value or len(value) > 16000:
        return set()
    try:
        tree = ast.parse(value)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    names = set()
    for index, item in enumerate(ast.walk(tree)):
        if index >= 4096:
            return set()
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
            names.add(item.id)
    return names


def source_literals(source):
    """Map prose blocks to exact parenthesized labels, scoped to same-page code.

    Reading-order adjacency avoids globally freezing ordinary words that happen
    to be variable names elsewhere in a paper. The complete printed parentheses
    are indivisible, while unparenthesized prose and explanations stay editable.
    """
    blocks = {block['id']:block for block in source['blocks']}
    order = source.get('reading_order', [])
    declared = {}
    result = {}

    def pages(block):
        return {location['page'] for location in block.get('provenance', [])
                if location.get('type') == 'pdf' and 'page' in location}

    for index, block_id in enumerate(order):
        block = blocks.get(block_id)
        if not block or block['kind'] not in {'paragraph', 'list_item'}:
            continue
        matches = list(PARENTHESIZED_NAME.finditer(block['normalized_text']))
        if not matches:
            continue
        names = set()
        for other_index in (index - 1, index + 1):
            if not 0 <= other_index < len(order):
                continue
            other = blocks.get(order[other_index])
            if not other or other['kind'] != 'code' or not pages(block) & pages(other):
                continue
            if other['id'] not in declared:
                declared[other['id']] = _defined_names(other)
            names.update(declared[other['id']])
        literals = {match[0] for match in matches if (match[1] or match[2]) in names}
        if literals:
            result[block_id] = sorted(literals, key=lambda value: (-len(value), value))
    return result
