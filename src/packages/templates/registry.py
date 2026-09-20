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
    v4 = {**v3, 'id': 'reader-v4', 'version': '4', 'css_path': 'src/packages/templates/reader-v4.css',
        'js_path': 'src/packages/templates/reader-v4.js',
        'css_sha256': '9d77a9e5ef0c9d74469416859168785bb32ccb92d518b921a5900620e4427cca', 'js_sha256': 'a31b109bcf2930a667721d6c9d0d333ca570fb6408c1ce017dca3830b5c08a13',
        'extra_assets': [
            {'source': 'res/vendor/katex-0.18.7/katex.min.js', 'path': 'math.js', 'media_type': 'text/javascript', 'sha256': '10a91b479cd927446ceb60409fb0d72b5d0d05eaf446c9e52fafd64058c84540'},
            {'source': 'res/vendor/katex-0.18.7/LICENSE', 'path': 'math-LICENSE.txt', 'media_type': 'text/plain', 'sha256': '766ccc1f306c885aa45542a9846bbd0a505b27a0374f146778171c2254ce18e3'},
        ]}
    v5 = {**v4, 'id': 'reader-v5', 'version': '5', 'css_path': 'src/packages/templates/reader-v5.css',
        'js_path': 'src/packages/templates/reader-v5.js',
        'css_sha256': 'ff43a09d9badb0c1cc3ac420c32dd3b4bde1eadadf34fc8ed9cbdb2a5de226e9',
        'js_sha256': '031cd44b8752e056a543470a7379c720f769f6d7071d45fdf271bab61f623b1a'}
    v6 = {**v5, 'id': 'reader-v6', 'version': '6', 'css_path': 'src/packages/templates/reader-v6.css',
        'js_path': 'src/packages/templates/reader-v6.js',
        'css_sha256': '6491c0bc918b97c49209f3dc275495bcac6e247f29c9dcbc969e8a5a397e450d', 'js_sha256': '1d056a06014cfcac522c4320126eacf39eb9877235eb0d8b82f3237c86e2a9b2'}
    v7 = {**v6, 'id': 'reader-v7', 'version': '7', 'css_path': 'src/packages/templates/reader-v7.css',
        'js_path': 'src/packages/templates/reader-v7.js',
        'css_sha256': 'c893cc66b5d1f0a8f27f79aff0db1b282d2371ad5192e59db9b09eadc1fd8803', 'js_sha256': '6325ec57e43b7c09e4c67af01c3701e1c12e8aea2d9abca3f62af7fd669a5166'}
    for entry in (v1, v2, v3, v4, v5, v6, v7):
        require(digest((root/entry['css_path']).read_bytes()) == entry['css_sha256'], 'TEMPLATE_HASH_MISMATCH')
        require(digest((root/entry['js_path']).read_bytes()) == entry['js_sha256'], 'TEMPLATE_HASH_MISMATCH')
    return [v1, v2, v3, v4, v5, v6, v7]


def get_template(template_id):
    entry = next((t for t in list_templates() if t['id'] == template_id), None)
    require(entry is not None, 'TEMPLATE_UNREGISTERED')
    return entry
