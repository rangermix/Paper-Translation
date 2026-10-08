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
    v8 = {**v7, 'id': 'reader-v8', 'version': '8', 'css_path': 'src/packages/templates/reader-v8.css',
        'js_path': 'src/packages/templates/reader-v8.js',
        'css_sha256': '5ed924407dc38d6f8e029cbb648875d7c5c32134b2f0045f93acf05a359eac74', 'js_sha256': 'd9c098ae5884cb498a093dae44d2b52400ef1d095c47b04d4314e68298b5b40a'}
    v9 = {**v8, 'id': 'reader-v9', 'version': '9', 'css_path': 'src/packages/templates/reader-v9.css',
        'css_sha256': '48229339217f22424dfe8957c8259fa80c384b59a46258d6f5b11149036833a1'}
    v10 = {**v9, 'id':'reader-v10', 'version':'10', 'kinds':kinds+['group'],
        'css_path':'src/packages/templates/reader-v10.css', 'js_path':'src/packages/templates/reader-v10.js',
        'css_sha256':'0223b6aad13f7505e872ece50285109b81069a5d57ca5ea571d7bf16f6c223e2', 'js_sha256':'d9c098ae5884cb498a093dae44d2b52400ef1d095c47b04d4314e68298b5b40a', 'renderer_version':'reader-python-10.0.0',
        'renderer_sha256':digest((root/'src/packages/publisher/rich_renderer.py').read_bytes()),
        'schema_versions':['3.0','4.0']}
    v11 = {**v10, 'id':'reader-v11', 'version':'11',
        'css_path':'src/packages/templates/reader-v11.css', 'js_path':'src/packages/templates/reader-v11.js',
        'css_sha256':'198a0ec29b829583ad9860357d8d17586f7f899c3bddf7455bb4333c6c958f01',
        'js_sha256':'66c98c7d5a66270b8c8e97f2e731793b1d8ae80324ad42e2670d8a43f0e533a4',
        'renderer_version':'reader-python-11.0.0',
        'renderer_sha256':digest((root/'src/packages/publisher/reader_v11.py').read_bytes())}
    v12 = {**v11, 'id':'reader-v12', 'version':'12',
        'renderer_version':'reader-python-12.0.0',
        'renderer_sha256':digest((root/'src/packages/publisher/reader_v12.py').read_bytes())}
    v13 = {**v12, 'id':'reader-v13', 'version':'13',
        'css_path':'src/packages/templates/reader-v13.css', 'js_path':'src/packages/templates/reader-v13.js',
        'css_sha256':'c8fb66b25404f4e190fe8f0bc595184a40b3ef1cff9d9e8fab88c66187f4a5bf', 'js_sha256':'d0434e374b27651c23c71b2bc09aeb0582833fa49792a7f2ccedd3be2dc1c046',
        'renderer_version':'reader-python-13.0.0',
        'renderer_sha256':digest((root/'src/packages/publisher/reader_v13.py').read_bytes()),
        'extra_assets': v12['extra_assets'] + [
            {'source':'res/vendor/reader-fonts/JetBrainsMono-Bold.woff2', 'path':'fonts/JetBrainsMono-Bold.woff2',
             'media_type':'font/woff2', 'sha256':'c503cc5ec5f8b2c7666b7ecda1adf44bd45f2e6579b2eba0fc292150416588a2'},
            {'source':'res/vendor/reader-fonts/JetBrainsMono-BoldItalic.woff2', 'path':'fonts/JetBrainsMono-BoldItalic.woff2',
             'media_type':'font/woff2', 'sha256':'3a013466c0eee979fb9d42c2d7a8887cd3645dc8b897cfc5b71781cf982efc5a'},
            {'source':'res/vendor/reader-fonts/JetBrainsMono-Italic.woff2', 'path':'fonts/JetBrainsMono-Italic.woff2',
             'media_type':'font/woff2', 'sha256':'cb6a1b246318ed3885d7dffa14a2609297fe80e9b8e500bea33b52fa312a36a4'},
            {'source':'res/vendor/reader-fonts/JetBrainsMono-OFL.txt', 'path':'fonts/JetBrainsMono-OFL.txt',
             'media_type':'text/plain', 'sha256':'30f0c136e3c88e422d0791acd97238870f9054a9729bc34cf2ff0d4ed8cac4ad'},
            {'source':'res/vendor/reader-fonts/JetBrainsMono-Regular.woff2', 'path':'fonts/JetBrainsMono-Regular.woff2',
             'media_type':'font/woff2', 'sha256':'a9cb1cd82332b23a47e3a1239d25d13c86d16c4220695e34b243effa999f45f2'},
            {'source':'res/vendor/reader-fonts/MiSans-Bold.woff2', 'path':'fonts/MiSans-Bold.woff2',
             'media_type':'font/woff2', 'sha256':'1c5a7515b61bc82baaa2e2c2fdae2032479fb9a99e09d4d021dc17314fc5939b'},
            {'source':'res/vendor/reader-fonts/MiSans-LICENSE.txt', 'path':'fonts/MiSans-LICENSE.txt',
             'media_type':'text/plain', 'sha256':'979ed309aec1118d2724fb683a0b36d2e96571fc94d2d6dce9aba7dae852e9aa'},
            {'source':'res/vendor/reader-fonts/MiSans-Regular.woff2', 'path':'fonts/MiSans-Regular.woff2',
             'media_type':'font/woff2', 'sha256':'d704c1a932c0bd7e8a071d276cd81c0ed0c9fecfa26ac234f4bed0559fe1cb2d'}
        ]}
    for entry in (v1, v2, v3, v4, v5, v6, v7, v8, v9, v10, v11, v12, v13):
        require(digest((root/entry['css_path']).read_bytes()) == entry['css_sha256'], 'TEMPLATE_HASH_MISMATCH')
        require(digest((root/entry['js_path']).read_bytes()) == entry['js_sha256'], 'TEMPLATE_HASH_MISMATCH')
    return [v1, v2, v3, v4, v5, v6, v7, v8, v9, v10, v11, v12, v13]


def get_template(template_id):
    entry = next((t for t in list_templates() if t['id'] == template_id), None)
    require(entry is not None, 'TEMPLATE_UNREGISTERED')
    return entry
