"""Reader v13 content with explicit online return and bilingual section labels.

Historical renderers and resources are unchanged. Offline exports remove the
online navigation while retaining the same content, anchors and reading controls.
"""
from copy import deepcopy
from urllib.parse import quote

from packages.ir import flatten_inline
from .reader_v12 import render_toc
from .reader_v13 import render_html as render_content


def render_html(ir, asset_paths, *, include_source=False):
    page = render_content(ir, asset_paths, include_source=include_source)
    source = ir['source_revision']
    blocks = {block['id']: block for block in source['blocks']}
    labels = deepcopy(blocks)
    results = {result['block_id']: result for result in ir['translation_revision']['results']}
    for block_id, block in labels.items():
        result = results.get(block_id, {})
        if block['kind'] == 'heading' and result.get('status') == 'translated':
            target = flatten_inline(result.get('target_inline', []), source['protected_atoms']).strip()
            original = block['normalized_text'].strip()
            if target and target != original:
                block['normalized_text'] = target + ' / ' + original
    old_toc = render_toc(source, blocks, original_labels=True)
    new_toc = render_toc(source, labels, original_labels=True).replace('aria-label="原文章节"', 'aria-label="双语章节"', 1)
    page = page.replace(old_toc.encode('utf-8'), new_toc.encode('utf-8'), 1)
    destination = '/#/documents/' + quote(ir['document']['id'], safe='')
    navigation = ('<nav class="reader-return" data-online-reader aria-label="返回文库">'
                  '<a data-return-document href="' + destination + '">返回文档</a>'
                  '<a data-return-search hidden>返回搜索结果</a></nav>')
    page = page.replace('<a href="original.pdf" download>原始 PDF</a>'.encode('utf-8'),
                        '<a href="original.pdf" download>原文 PDF</a>'.encode('utf-8'), 1)
    return page.replace(b'<nav class="toolbar"', navigation.encode('utf-8') + b'<nav class="toolbar"', 1)
