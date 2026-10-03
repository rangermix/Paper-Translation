import hashlib
import io
import json
import tarfile

import httpx
import pytest


def fixture_model():
    payload = b'synthetic weights'
    return {'id': 'sample', 'label': 'Sample', 'runtime': 'mlx', 'family': 'hy', 'bits': 8,
            'format': 'safetensors', 'repo': 'example/sample', 'revision': 'a' * 40,
            'context_size': 8192, 'files': [{'path': 'model.safetensors', 'size': len(payload),
                'sha256': hashlib.sha256(payload).hexdigest()}]}, payload


def test_catalog_has_exact_requested_quantizations_and_immutable_files():
    from packages.local_models.catalog import models, artifact
    entries = models()
    assert [(m['label'], m['bits']) for m in entries] == [
        ('Hy-MT2-1.8B Q8', 8), ('MiLMMT-46-4B Q4', 4), ('Hy-MT2-7B Q4', 4), ('MiLMMT-46-12B Q4', 4),
        ('Hy-MT2-1.8B BF16 Safetensors', 16), ('Hy-MT2-1.8B Q4_K_M GGUF', 4),
        ('Hy-MT2-7B Q4_K_M GGUF', 4),
        ('MiLMMT-46-1B Q4_K_M GGUF', 4), ('MiLMMT-46-4B Q4_K_M GGUF', 4),
        ('MiLMMT-46-12B Q4_K_M GGUF', 4),
        ('MiniCPM5-1B Q4 analyst', 4)]
    for model in entries:
        assert model['runtime'] in {'mlx', 'vllm', 'llama.cpp'}
        assert model['parameter_size'] and model['quantization']
        assert len(model['revision']) == 40
        assert all(len(f['sha256']) == 64 and f['size'] > 0 for f in model['files'])
        assert artifact(model)['id'].startswith('sha256:')


def test_download_is_pinned_hash_checked_and_cached(tmp_path):
    from packages.local_models.download import download
    model, payload = fixture_model()
    calls = []
    def handler(request):
        calls.append(request)
        assert '/' + 'a' * 40 + '/' in str(request.url)
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        download(model, tmp_path, client)
        download(model, tmp_path, client)
    assert len(calls) == 1
    assert (tmp_path / 'model.safetensors').read_bytes() == payload


def test_corrupt_download_never_published_and_retry_recovers(tmp_path):
    from packages.local_models.download import download
    model, payload = fixture_model()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'wrong'))) as client:
        with pytest.raises(ValueError, match='LOCAL_MODEL_HASH'):
            download(model, tmp_path, client)
    assert not (tmp_path / 'model.safetensors').exists()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=payload))) as client:
        download(model, tmp_path, client)
    assert (tmp_path / 'model.safetensors').read_bytes() == payload


def test_packaging_preserves_weights_and_model_digest(tmp_path):
    from packages.local_models.catalog import artifact
    from packages.local_models.download import archive
    model, payload = fixture_model()
    (tmp_path / 'model.safetensors').write_bytes(payload)
    data = b''.join(archive(model, tmp_path))
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        manifest = tar.extractfile('manifest.json').read()
        assert 'sha256:' + hashlib.sha256(manifest).hexdigest() == artifact(model)['id']
        desc = json.loads(manifest)['layers'][0]
        assert desc['annotations']['org.cncf.model.filepath'] == 'model.safetensors'
        assert tar.extractfile('blobs/sha256/' + desc['digest'].split(':')[1]).read() == payload


@pytest.mark.parametrize('size', [8 ** 11 - 1, 8 ** 11, 10_591_220_088])
def test_packaging_streams_large_weight_headers_with_exact_size(tmp_path, size):
    from packages.local_models.download import archive
    model, _ = fixture_model()
    model['files'][0]['size'] = size
    name = 'blobs/sha256/' + model['files'][0]['sha256']
    # No weight file exists: producing and parsing the header needs no payload,
    # including Chandra's single 10,591,220,088-byte safetensors member.
    stream = archive(model, tmp_path)
    header = next(stream)
    stream.close()
    assert len(header) <= 1536
    with tarfile.open(fileobj=io.BytesIO(header), mode='r|') as tar:
        member = tar.next()
        assert member.name == name
        assert member.size == size
        assert member.mode == 0o644
        assert member.isfile()
    if size < 8 ** 11:
        original = tarfile.TarInfo(name)
        original.size = size
        original.mode = 0o644
        assert header == original.tobuf(format=tarfile.USTAR_FORMAT)


def test_unknown_models_and_paths_are_rejected(tmp_path):
    from packages.local_models.catalog import get_model
    from packages.local_models.download import download
    with pytest.raises(ValueError, match='LOCAL_MODEL_UNKNOWN'):
        get_model('https://evil.example/model')
    model, _ = fixture_model()
    model['files'][0]['path'] = '../escape'
    with pytest.raises(ValueError, match='LOCAL_MODEL_PATH'):
        download(model, tmp_path, None)
