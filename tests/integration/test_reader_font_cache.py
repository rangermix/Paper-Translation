"""Shared vendor fonts cache across readers without changing stored publications."""
from pathlib import PurePosixPath

import pytest

from packages.domain.models import Artifact
from packages.ir import canonical_bytes, digest
from packages.paths import ROOT
from packages.publisher import verify_artifact
from packages.storage import file_hash
from packages.templates.registry import get_template
from tests.integration.test_publication_lifecycle import drain, seal_and_publish
from tests.support import seed_editor

pytestmark = pytest.mark.postgres
PUBLIC_CACHE = 'public, max-age=31536000, immutable'
PRIVATE_ALIAS_CACHE = 'private, max-age=31536000, immutable'


def fonts():
    return [asset for asset in get_template('reader-v13')['extra_assets']
            if asset['media_type'] == 'font/woff2']


def shared_url(font):
    return f'/reader-assets/fonts/{font["sha256"]}/{PurePosixPath(font["path"]).name}'


def stored_hashes(directory):
    return {file.relative_to(directory).as_posix(): file_hash(file)
            for file in directory.rglob('*') if file.is_file()}


@pytest.fixture
def published_reader(client, database):
    db, cfg = database
    seed_editor(db, cfg)
    artifact_id, index = seal_and_publish(client, db, cfg, 1, 1, 'font-cache')
    drain(db, cfg)
    return artifact_id, index.parent


def test_registered_fonts_get_head_and_conditional_cache_without_documents(client, monkeypatch):
    # Shared vendor bytes need neither document records nor an available database.
    monkeypatch.setattr(client.app.state, 'db', None)
    for font in fonts():
        response = client.get(shared_url(font))
        expected = (ROOT / font['source']).read_bytes()
        assert response.status_code == 200
        assert response.content == expected
        assert response.headers['content-type'] == 'font/woff2'
        assert response.headers['cache-control'] == PUBLIC_CACHE
        assert response.headers['etag'] == f'"{font["sha256"]}"'
        assert int(response.headers['content-length']) == len(expected)
        head = client.head(shared_url(font))
        assert head.status_code == 200 and head.content == b''
        for name in ('content-type', 'content-length', 'etag', 'cache-control'):
            assert head.headers[name] == response.headers[name]

    font = fonts()[0]
    etag = f'"{font["sha256"]}"'
    for method in (client.get, client.head):
        for value in (etag, 'W/' + etag, '"different", ' + etag,
                      ' W/"different", W/' + etag + ' ', '*'):
            response = method(shared_url(font), headers={'If-None-Match': value})
            assert response.status_code == 304 and response.content == b''
            assert response.headers['etag'] == etag
            assert response.headers['cache-control'] == PUBLIC_CACHE
        unmatched = method(shared_url(font), headers={'If-None-Match': '"different"'})
        assert unmatched.status_code == 200


def test_shared_font_route_rejects_unknown_nonfont_and_malformed_paths(client):
    font = fonts()[0]
    filename = PurePosixPath(font['path']).name
    license_asset = next(asset for asset in get_template('reader-v13')['extra_assets']
                         if asset['path'] == 'fonts/MiSans-LICENSE.txt')
    paths = [
        f'/reader-assets/fonts/{"0" * 64}/{filename}',
        f'/reader-assets/fonts/{font["sha256"]}/unregistered.woff2',
        f'/reader-assets/fonts/not-a-digest/{filename}',
        f'/reader-assets/fonts/{font["sha256"].upper()}/{filename}',
        shared_url(license_asset),
        f'/reader-assets/fonts/{font["sha256"]}/nested/{filename}',
        f'/reader-assets/fonts/{font["sha256"]}/%2e%2e%2fMiSans-Regular.woff2',
        f'/reader-assets/fonts/{font["sha256"]}/..%5cMiSans-Regular.woff2',
        '/reader-assets/fonts', '/reader-assets/missing', '/reader-assets',
    ]
    for path in paths:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 404, (path, response.text)
        assert 'public' not in response.headers.get('cache-control', '')
        assert 'text/html' not in response.headers.get('content-type', '')


@pytest.mark.parametrize('missing', [False, True])
def test_shared_corrupt_font_fails_before_conditional_response(client, monkeypatch, tmp_path, missing):
    from apps.api import reader_assets

    font = fonts()[0]
    if not missing:
        (tmp_path / 'corrupt.woff2').write_bytes(b'not the registered font bytes')
    monkeypatch.setattr(reader_assets, 'ROOT', tmp_path)
    monkeypatch.setattr(reader_assets, 'registered_font',
                        lambda sha256, filename: {**font, 'source': 'corrupt.woff2'})
    for method in (client.get, client.head):
        response = method(shared_url(font), headers={'If-None-Match': '*'})
        assert response.status_code == 409
        assert 'public' not in response.headers.get('cache-control', '')
        if method == client.get:
            assert response.json()['error']['code'] == 'READER_FONT_CORRUPT'


def test_two_artifacts_reuse_one_font_url_without_rewriting_publications(client, database, published_reader):
    db, cfg = database
    first_id, first_dir = published_reader
    first_hashes = stored_hashes(first_dir)
    second_id, second_index = seal_and_publish(client, db, cfg, 1, 2, 'font-cache-second')
    drain(db, cfg)
    second_dir = second_index.parent
    second_hashes = stored_hashes(second_dir)
    font = next(item for item in fonts() if item['path'] == 'fonts/MiSans-Regular.woff2')
    for artifact_id, directory in ((first_id, first_dir), (second_id, second_dir)):
        alias = f'/artifacts/{artifact_id}/{font["path"]}'
        for method in (client.get, client.head):
            response = method(alias, follow_redirects=False)
            assert response.status_code == 307
            assert response.headers['location'] == shared_url(font)
            assert response.headers['cache-control'] == PRIVATE_ALIAS_CACHE
        followed = client.get(alias)
        assert followed.status_code == 200
        assert followed.content == (directory / font['path']).read_bytes()
        assert followed.headers['cache-control'] == PUBLIC_CACHE
        # Content, script, styles and license files do not become public assets.
        for name in ('index.html', 'reader.css', 'reader.js', 'fonts/MiSans-LICENSE.txt'):
            response = client.get(f'/artifacts/{artifact_id}/{name}', follow_redirects=False)
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'private, no-cache'
            assert response.content == (directory / name).read_bytes()
        verify_artifact(directory)
    assert stored_hashes(first_dir) == first_hashes
    assert stored_hashes(second_dir) == second_hashes


def test_artifact_font_redirect_requires_intact_artifact(client, published_reader):
    artifact_id, directory = published_reader
    font = fonts()[0]
    assert client.get(f'/artifacts/{artifact_id}/fonts/unlisted.woff2').status_code == 404
    assert client.get(f'/artifacts/not-an-artifact/{font["path"]}').status_code == 404
    # Damage another file to prove the complete artifact is checked before redirect.
    index = directory / 'index.html'
    index.write_bytes(index.read_bytes() + b'\ncorrupt fixture')
    response = client.get(f'/artifacts/{artifact_id}/{font["path"]}', follow_redirects=False)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'ARTIFACT_CORRUPT'
    assert 'location' not in response.headers
    assert 'immutable' not in response.headers.get('cache-control', '')


@pytest.mark.parametrize('difference', ['digest', 'path', 'media_type'])
def test_unregistered_historical_fonts_keep_private_artifact_bytes(client, database, published_reader, difference):
    db, _ = database
    artifact_id, directory = published_reader
    manifest = verify_artifact(directory)
    font = fonts()[0]
    entry = next(item for item in manifest['files'] if item['path'] == font['path'])
    if difference == 'digest':
        (directory / entry['path']).write_bytes(b'authored historical font fixture')
        entry['sha256'] = file_hash(directory / entry['path'])
        entry['byte_size'] = (directory / entry['path']).stat().st_size
    elif difference == 'path':
        original = directory / entry['path']
        entry['path'] = 'historical-fonts/' + PurePosixPath(entry['path']).name
        destination = directory / entry['path']
        destination.parent.mkdir()
        original.rename(destination)
    else:
        entry['media_type'] = 'application/octet-stream'
    # Assemble a valid authored historical artifact in the disposable test store.
    manifest['content_digest'] = digest(manifest['files'])
    (directory / 'manifest.json').write_bytes(canonical_bytes(manifest))
    with db.transaction() as session:
        session.get(Artifact, artifact_id).manifest_hash = digest(manifest)
    verify_artifact(directory)
    before = stored_hashes(directory)
    response = client.get(f'/artifacts/{artifact_id}/{entry["path"]}', follow_redirects=False)
    assert response.status_code == 200
    assert response.content == (directory / entry['path']).read_bytes()
    assert response.headers['cache-control'] == 'private, no-cache'
    assert response.headers['etag'] == f'"{entry["sha256"]}"'
    assert 'location' not in response.headers
    assert stored_hashes(directory) == before
