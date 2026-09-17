from packages.paths import ROOT
from packages.domain.errors import require
from packages.ir import digest
from packages.publisher.renderer import CSS_HASH, RENDERER_VERSION


V2_CSS_HASH = 'c28618b5c6de5f3c6fbc84464f8f3eb5748793e45e4e3c4313faf39bb4077a25'
V2_JS_HASH = 'acd9ed87b078ba30dfe61e1d8f46fc4d07e88c06b0a1b5639edc964dc74af8c8'
V3_CSS_HASH = '3cb67a6b9af14ce5a71d6a444b308875aa910116f44742a7bafd2fc6ba041057'
V3_JS_HASH = 'eaf086e189cf7133a63ea5b8c9666072f97f7617c55bcaa93c9b21a838dfa426'


def list_templates():
    root = ROOT
    require(digest((root / 'res/reference/reader-v1.css').read_bytes()) == CSS_HASH, 'TEMPLATE_HASH_MISMATCH')
    kinds = ['heading', 'paragraph', 'list_item', 'code', 'math', 'figure', 'caption', 'table', 'table_cell', 'footnote', 'reference']
    v1 = {'id': 'reader-v1', 'version': '1', 'css_sha256': CSS_HASH,
        'js_sha256': digest((root / 'src/packages/publisher/reader.js').read_bytes()),
        'renderer_version': RENDERER_VERSION, 'renderer_sha256': digest((root / 'src/packages/publisher/renderer.py').read_bytes()),
        'css_path': 'res/reference/reader-v1.css', 'js_path': 'src/packages/publisher/reader.js', 'kinds': kinds,
        'safety_review': 'frozen-reference-v1'}
    v2 = {**v1, 'id': 'reader-v2', 'version': '2', 'css_path': 'src/packages/templates/reader-v2.css',
        'js_path': 'src/packages/templates/reader-v2.js', 'css_sha256': V2_CSS_HASH, 'js_sha256': V2_JS_HASH,
        'safety_review': '.agent/tmp/reports/core-evidence/reader-v2-review.md'}
    v3 = {**v2, 'id': 'reader-v3', 'version': '3', 'css_path': 'src/packages/templates/reader-v3.css',
        'js_path': 'src/packages/templates/reader-v3.js', 'css_sha256': V3_CSS_HASH, 'js_sha256': V3_JS_HASH,
        'safety_review': 'docs/workflows.md'}
    for entry in (v1, v2, v3):
        require(digest((root/entry['css_path']).read_bytes()) == entry['css_sha256'], 'TEMPLATE_HASH_MISMATCH')
        require(digest((root/entry['js_path']).read_bytes()) == entry['js_sha256'], 'TEMPLATE_HASH_MISMATCH')
    return [v1, v2, v3]


def get_template(template_id):
    entry = next((t for t in list_templates() if t['id'] == template_id), None)
    require(entry is not None, 'TEMPLATE_UNREGISTERED')
    return entry
