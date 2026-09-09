import json
import copy
import tempfile
import unittest
import zipfile
from pathlib import Path

from packages.ir import block_hash, digest
from packages.publisher import Publisher, export_bundle, export_single_html, verify_artifact

ROOT = Path(__file__).resolve().parents[2]


class Publishing(unittest.TestCase):
    def setUp(self):
        self.ir = json.loads((ROOT / 'fixtures/sample-document-v3.json').read_text('utf-8'))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def build(self, name='artifact', include_source=False):
        path = self.path / name
        Publisher().build(self.ir, ROOT, path, include_source=include_source)
        return path

    def test_all_blocks_once_and_css_frozen(self):
        path = self.build()
        html = (path / 'index.html').read_text('utf-8')
        for block in self.ir['source_revision']['blocks']:
            self.assertEqual(html.count('id="b-'+block['id']+'"'), 1, block['id'])
        self.assertEqual((path/'reader.css').read_bytes(), (ROOT/'reference/reader-v1.css').read_bytes())
        self.assertIn('href="#b-p2"', html)
        self.assertNotIn('original.pdf', html)

    def test_long_plain_tokens_keep_text_and_wrap_without_changing_frozen_css(self):
        path=self.build()
        html=(path/'index.html').read_text('utf8')
        self.assertIn('<body style="overflow-wrap:anywhere">',html)
        self.assertEqual((path/'reader.css').read_bytes(),(ROOT/'reference/reader-v1.css').read_bytes())

    def test_deterministic_builds_and_zip(self):
        a,b = self.build('a'),self.build('b')
        self.assertEqual(verify_artifact(a),verify_artifact(b))
        x = export_bundle(a,self.path/'a.zip')
        y = export_bundle(b,self.path/'b.zip')
        self.assertEqual(x.read_bytes(),y.read_bytes())

    def test_single_html_embeds_resources(self):
        path = self.build(include_source=True)
        single = export_single_html(path,self.path/'single.html',include_source=True).read_text('utf-8')
        self.assertIn('data:image/png;base64,',single)
        self.assertIn('data:application/pdf;base64,',single)
        self.assertNotIn('src="reader.js"',single)
        self.assertNotIn('href="reader.css"',single)

    def test_single_html_csp_hash_matches_html_normalized_crlf_script(self):
        import base64,re
        path=self.build();js=(path/'reader.js').read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (path/'reader.js').write_bytes(js)
        # A valid historical artifact can contain CRLF resources; only this temporary artifact is changed.
        manifest=json.loads((path/'manifest.json').read_text('utf8'))
        entry=next(e for e in manifest['files'] if e['path']=='reader.js');entry.update(byte_size=len(js),sha256=digest(js))
        manifest['content_digest']=digest(manifest['files']);(path/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
        before={p.name:p.read_bytes() for p in path.iterdir() if p.is_file()}
        single=export_single_html(path,self.path/'crlf.html').read_bytes().decode('utf8')
        inline=re.search(r'<script defer>(.*?)</script>',single,re.S)[1]
        browser_text=inline.replace('\r\n','\n').replace('\r','\n')
        expected=base64.b64encode(__import__('hashlib').sha256(browser_text.encode()).digest()).decode()
        self.assertIn("script-src 'sha256-"+expected+"'",single)
        self.assertEqual(before,{p.name:p.read_bytes() for p in path.iterdir() if p.is_file()})

    def test_export_default_excludes_pdf_and_control(self):
        path = self.build(include_source=True)
        single = export_single_html(path,self.path/'without.html').read_text('utf-8')
        self.assertNotIn('original.pdf',single)
        self.assertNotIn('data:application/pdf',single)
        bundle=export_bundle(path,self.path/'without.zip')
        with zipfile.ZipFile(bundle) as archive:
            self.assertNotIn('original.pdf',archive.namelist())
            manifest=json.loads(archive.read('manifest.json'))
            self.assertFalse(manifest['include_source'])

    def test_tampered_artifact_is_rejected(self):
        path = self.build()
        (path/'index.html').write_text('half',encoding='utf-8')
        with self.assertRaises(ValueError):
            verify_artifact(path)

    def test_existing_artifact_never_overwritten(self):
        path = self.build()
        original = (path/'index.html').read_bytes()
        with self.assertRaises(FileExistsError):
            Publisher().build(self.ir,ROOT,path)
        self.assertEqual(original,(path/'index.html').read_bytes())

    def test_unsupported_template_rejected(self):
        self.ir['render']['template_id']='arbitrary'
        with self.assertRaises(ValueError):
            self.build()

    def test_registered_v2_uses_its_independent_resources(self):
        from packages.templates.registry import get_template
        template = get_template('reader-v2')
        self.ir['render']['template_id'] = template['id']
        self.ir['render']['template_sha256'] = template['css_sha256']
        path = self.build('v2')
        manifest = verify_artifact(path)
        self.assertEqual(manifest['template_id'], 'reader-v2')
        self.assertEqual(manifest['template_sha256'], template['css_sha256'])
        self.assertEqual((path/'reader.css').read_bytes(), (ROOT/template['css_path']).read_bytes())
        self.assertEqual((path/'reader.js').read_bytes(), (ROOT/template['js_path']).read_bytes())
        self.assertNotEqual((path/'reader.css').read_bytes(), (ROOT/'reference/reader-v1.css').read_bytes())

    def test_v2_rejects_v1_hash(self):
        self.ir['render']['template_id'] = 'reader-v2'
        with self.assertRaisesRegex(ValueError, 'TEMPLATE_HASH_MISMATCH'):
            self.build('wrong-hash')

    def test_toc_follows_heading_levels_without_changing_frozen_css(self):
        source = self.ir['source_revision']
        self.ir['translation_revision']['results'][0]['warnings'] = ['Optional review <incomplete>']
        for name, level in [('chapter', 2), ('detail', 4), ('next-chapter', 2)]:
            block = copy.deepcopy(source['blocks'][0])
            block.update(id=name, order=len(source['blocks']), parent_id='title', raw_text=name, normalized_text=name,
                source_inline=[{'type': 'text', 'text': name}], normalization_edits=[], attributes={'level': level})
            block['source_hash'] = block_hash(block, source['protected_atoms'])
            source['blocks'].append(block)
            source['reading_order'].append(name)
            target = copy.deepcopy(self.ir['translation_revision']['results'][0])
            target.update(block_id=name, source_hash=block['source_hash'], target_inline=[{'type': 'text', 'text': name}], warnings=[name+' <risk>'])
            self.ir['translation_revision']['results'].append(target)
        path = self.build()
        html = (path/'index.html').read_text('utf-8')
        expected = '<ol><li><a href="#b-chapter">chapter</a><ol><li><a href="#b-detail">detail</a></li></ol></li><li><a href="#b-next-chapter">next-chapter</a></li></ol>'
        self.assertIn(expected, html)
        self.assertIn('Optional review &lt;incomplete&gt;', html)
        self.assertIn('chapter &lt;risk&gt;', html)
        self.assertEqual((path/'reader.css').read_bytes(), (ROOT/'reference/reader-v1.css').read_bytes())


if __name__ == '__main__':
    unittest.main()
