"""API edits, sealed publication and both exports must retain attack strings as text."""
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import uuid
import zipfile

import pytest

from tests.support import seed_editor
from tests.integration.test_publication_lifecycle import drain, seal_and_publish

pytestmark = pytest.mark.postgres
PAYLOAD = '</script><script>window.ATTACK_RAN=true</script><img src="https://attacker.invalid/x" onerror="window.ATTACK_RAN=true"> CSS @import url(https://attacker.invalid/style); 😀 𠮷'


class Nodes(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags, self.text = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def assert_safe_literal(html):
    dom = Nodes(html)
    assert PAYLOAD in ''.join(dom.text)
    for tag, attrs in dom.tags:
        assert not any(name.lower().startswith('on') for name in attrs)
        assert not any('attacker.invalid' in (attrs.get(name) or '') for name in ('href', 'src', 'style'))
    assert '&lt;script&gt;window.ATTACK_RAN=true&lt;/script&gt;' in html


def test_hostile_target_roundtrips_through_reader_and_offline_exports(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    for index, href in enumerate(('javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'https://attacker.invalid/')):
        bad = client.patch('/api/v1/drafts/draft_fixture/segments/item', json={'base_segment_version': 1,
            'reason': 'Hostile node regression', 'target_inline': [{'type': 'link', 'href': href, 'text': 'new link'}]},
            headers={'If-Match': '"1"', 'Idempotency-Key': f'hostile-link-{index}'})
        assert bad.status_code == 422 and bad.json()['error']['code'] == 'TARGET_AST_INVALID'
    changed = client.patch('/api/v1/drafts/draft_fixture/segments/item', json={'base_segment_version': 1,
        'reason': 'Controlled literal escaping fixture', 'target_inline': [{'type': 'text', 'text': PAYLOAD}]},
        headers={'If-Match': '"1"', 'Idempotency-Key': 'literal-hostile-text'})
    assert changed.status_code == 200, changed.text
    artifact, path = seal_and_publish(client, db, cfg, 2, 1, 'hostile-literal')
    online = client.get('/artifacts/' + artifact + '/index.html')
    assert online.status_code == 200
    assert_safe_literal(online.text)
    csp = online.headers['content-security-policy']
    # Browser enforces the intersection of the app header and reader meta CSP.
    policies = [attrs['content'] for tag, attrs in Nodes(online.text).tags
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'content-security-policy']
    assert any("connect-src 'none'" in policy for policy in policies) and "object-src 'none'" in csp
    for traversal in ('%2e%2e%2f%2e%2e%2finternal%2fdb_password', 'unlisted.json', '%2fetc%2fpasswd', '..%5c..%5cinternal%5cdb_password'):
        assert client.get('/artifacts/' + artifact + '/' + traversal).status_code in (400, 404, 422)
    drain(db, cfg)
    evidence = Path('.agent/tmp/evidence/hostile-reader') / uuid.uuid4().hex
    evidence.mkdir(parents=True)
    (evidence / 'online.html').write_text(online.text, encoding='utf-8')
    for format in ('single_html', 'bundle'):
        queued = client.post('/api/v1/artifacts/' + artifact + '/exports', json={'format': format, 'include_source': False},
            headers={'Idempotency-Key': 'hostile-export-' + format})
        assert queued.status_code == 202
        drain(db, cfg)
        exported = client.get('/api/v1/exports/' + queued.json()['id'] + '/download')
        assert exported.status_code == 200
        if format == 'single_html':
            assert_safe_literal(exported.text)
            (evidence / 'single.html').write_bytes(exported.content)
        else:
            with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                for name in archive.namelist():
                    assert not Path(name).is_absolute() and '..' not in Path(name).parts
                assert_safe_literal(archive.read('index.html').decode('utf-8'))
                archive.extractall(evidence / 'bundle')
            (evidence / 'bundle.zip').write_bytes(exported.content)
    (evidence / 'verification.json').write_text(json.dumps({'status': 'passed', 'scope': 'real PostgreSQL/API/worker; authored hostile literal, no Provider',
        'artifact_id': artifact, 'payload': PAYLOAD, 'csp': csp, 'formats': ['online', 'single_html', 'bundle']}, ensure_ascii=False, indent=2), encoding='utf-8')
