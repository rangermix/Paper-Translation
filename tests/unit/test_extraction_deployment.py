"""Static deployment contracts; these do not certify Docker or real inference."""
import json
from pathlib import Path
import re
import tomllib

import pytest
import yaml


def compose_mode(mode='CPU'):
    text = Path('compose.example.yaml').read_text()
    if mode != 'CPU':
        text = re.sub(r'# --- BEGIN CPU MODE.*?# --- END CPU MODE ---', '', text, flags=re.S)
        pattern = rf'# --- BEGIN {mode} MODE[^\n]*\n(.*?)# --- END {mode} MODE ---'
        text = re.sub(pattern, lambda match: re.sub(r'^# ?', '', match[1], flags=re.M), text, flags=re.S)
    return yaml.safe_load(text)


def test_provider_setup_uses_managed_storage_without_external_defaults():
    doc = compose_mode()
    assert not doc.get('secrets')
    for name, service in doc['services'].items():
        assert not service.get('secrets'), name
        assert not {'PROVIDER_PROFILE_FILE', 'PROVIDER_KEY_FILE'} & service.get('environment', {}).keys(), name
        mounts = service.get('volumes', [])
        assert not any('provider-profile.json' in str(v) or 'provider_key' in str(v) for v in mounts), name
        managed = [v for v in mounts if '/provider_config' in str(v)]
        if name in {'init', 'app', 'worker'}:
            assert managed == ['provider_config:/provider_config' + (':ro' if name == 'worker' else '')]
        else:
            assert not managed, name


def test_test_services_only_depend_on_their_private_database():
    doc = compose_mode()
    services = doc['services']
    assert {'tests', 'test-db', 'checks'} <= services.keys()
    assert services['tests']['profiles'] == ['tests']
    assert set(services['tests']['depends_on']) == {'test-db'}
    assert services['test-db']['profiles'] == ['tests']
    assert not services['test-db'].get('volumes')
    assert '/var/lib/postgresql/data' in services['test-db']['tmpfs']
    for name in ('tests', 'test-db'):
        assert services[name]['networks'] == ['test_backend']
    # Docker does not publish the documented host-test port on an internal-only network.
    assert not doc['networks']['test_backend'].get('internal', False)
    assert services['test-db']['ports'] == ['127.0.0.1:${TEST_DB_PORT:-55439}:5432']
    for name in ('tests', 'checks'):
        assert services[name]['build']['context'] == '.'
        assert services[name]['build']['dockerfile'] == 'tests/Dockerfile'
    checks = services['checks']
    assert checks['network_mode'] == 'none' and checks['read_only']
    assert not any(checks.get(key) for key in ('depends_on', 'volumes', 'ports', 'secrets'))


def test_optional_model_services_do_not_start_with_the_core_stack():
    services = compose_mode()['services']
    assert {'local-model-init', 'local-translator', 'model-export'} <= services.keys()
    for name in ('local-model-init', 'local-translator'):
        assert services[name]['profiles'] == ['local-translation']
        assert services[name]['volumes'] == ['local_translation_models:/model_cache']
    assert set(services['local-translator']['depends_on']) == {'local-model-init'}
    exporter = services['model-export']
    assert exporter['profiles'] == ['model-tools']
    assert exporter['network_mode'] == 'none' and exporter['read_only']
    assert exporter['volumes'] == ['parser_models:/opt/docling/models:ro']
    assert {name for name, s in services.items() if not s.get('profiles')} == {
        'init', 'db', 'migrate', 'app', 'worker', 'parser', 'parser-models'}


def test_release_environment_example_names_are_consumed_by_production_compose():
    example = Path('.env.example').read_text()
    compose = Path('compose.example.yaml').read_text()
    documented = set(re.findall(r'^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=', example, re.MULTILINE))
    consumed = set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)', compose))
    assert documented <= consumed, f'Unused deployment settings: {sorted(documented - consumed)}'


def test_cpu_and_cuda_keep_parser_isolation_and_one_unified_image_recipe():
    base = compose_mode()
    gpu = compose_mode('CUDA')['services']['parser']
    assert base['services']['parser']['networks'] == ['parser_model_control']
    assert gpu['networks'] == ['parser_model_control'] and 'network_mode' not in gpu
    assert base['networks']['parser_model_control']['internal'] is True
    assert gpu['build']['args']['PARSER_FLAVOR'] == 'cuda'
    assert gpu['deploy']['resources']['reservations']['devices'] == [
        {'driver': 'nvidia', 'count': 1, 'capabilities': ['gpu']}]
    recipe = Path('deployment/images/parser.Dockerfile').read_text()
    assert 'FROM dependencies-${PARSER_FLAVOR} AS dependencies' in recipe
    assert '/app/.venv-paddle' in recipe


def test_mlx_is_compose_managed_and_does_not_mount_host_credentials():
    doc = compose_mode('MLX')
    parser = doc['services']['parser']
    assert parser['models'] == ['paddle_extraction']
    assert 'network_mode' not in parser
    assert parser['networks'] == ['parser_model_control', 'model_inference']
    assert not set(parser) & {'ports', 'secrets'}
    assert parser['volumes'] == ['parser_inputs:/inputs:ro', 'parser_outputs:/outputs', 'parser_models:/opt/docling/models:ro']
    assert 'PADDLE_MLX_MODEL_ID' in parser['environment']
    assert doc['models']['paddle_extraction']['context_size'] == 8192
    assert not Path('src/workers/mlx_server.py').exists()


def test_cuda_dependency_graphs_are_separate_and_frozen():
    for project, gpu_package in [('cuda', 'torch'), ('cuda-paddle', 'paddlepaddle-gpu')]:
        root = Path('deployment') / project
        config = tomllib.loads((root / 'pyproject.toml').read_text())
        lock = tomllib.loads((root / 'uv.lock').read_text())
        assert not config['tool']['uv'].get('override-dependencies')
        packages = {row['name']: row for row in lock['package']}
        assert gpu_package in packages
        assert 'paddlepaddle' in packages if project == 'cuda' else 'paddlepaddle' not in packages
        assert '+cu126' in packages['torch']['version'] if project == 'cuda' else '+cpu' in packages['torch']['version']


def test_dmr_client_is_portable_and_model_preparation_has_no_content_or_secret_mounts():
    doc = compose_mode('DMR')
    parser = doc['services']['parser']
    assert parser['build']['args']['PARSER_FLAVOR'] == 'runner'
    assert 'platform' not in parser and 'models' not in parser
    assert parser['networks'] == ['parser_model_control', 'model_inference']
    manager = doc['services']['parser-models']
    assert manager['volumes'] == ['parser_models:/model_cache']
    assert manager['networks'] == ['parser_model_control', 'model_inference']
    assert not any(manager.get(key) for key in ('ports', 'secrets', 'models'))
    recipe = Path('deployment/images/parser.Dockerfile').read_text()
    assert 'download_parser_models' not in recipe and 'COPY --from=models' not in recipe


def test_native_cpu_cuda_parser_versions_match_model_manifests():
    native = json.loads(Path('deployment/parser-models.lock.json').read_text())
    vision = json.loads(Path('deployment/parser-vlm-models.lock.json').read_text())
    for path in ('uv.lock', 'deployment/cuda/uv.lock'):
        packages = {row['name']: row for row in tomllib.loads(Path(path).read_text())['package']}
        assert packages['docling']['version'] == native['docling_version']
        assert packages['transformers']['version'] == vision['transformers_version']
    tele = tomllib.loads(Path('deployment/teleocr/uv.lock').read_text())
    packages = {row['name']: row for row in tele['package']}
    model = next(row for row in vision['models'] if row['id'] == 'teleocr-v1')
    assert packages['transformers']['version'] == model['transformers_version'] == '4.57.1'
    assert 'torch' not in packages
    recipe = Path('deployment/images/parser.Dockerfile').read_text()
    assert '/app/.venv-tele' in recipe and 'parser-native.pth' in recipe


def test_export_refuses_overwrite_and_verifies_before_copy(tmp_path, monkeypatch):
    from tools.export_parser_model import export_model
    root = tmp_path / 'weights'; root.mkdir()
    (root / 'paddle').mkdir(); (root / 'paddle' / 'weight').write_bytes(b'locked')
    model = {'repo_id': 'PaddlePaddle/PaddleOCR-VL-1.6', 'local_directory': 'paddle',
        'revision': 'fixed', 'files': [{'path': 'weight'}]}
    calls = []
    monkeypatch.setattr('tools.export_parser_model.verify_models', lambda path, profile: calls.append(path) or {'repositories': [model]})
    target = tmp_path / 'export'
    assert export_model(root, target) == 'fixed'
    assert calls == [root]
    assert (target / 'weight').read_bytes() == b'locked'
    with pytest.raises(ValueError, match='MODEL_EXPORT_DESTINATION_EXISTS'):
        export_model(root, target)
