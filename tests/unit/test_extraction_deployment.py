"""Static deployment contracts; these do not certify Docker or real inference."""
import json
from pathlib import Path
import re
import tomllib

import pytest
import yaml


def compose_mode():
    return yaml.safe_load(Path('compose.example.yaml').read_text())


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
    assert {'local-model-init', 'local-translator'} <= services.keys()
    for name in ('local-model-init', 'local-translator'):
        assert services[name]['profiles'] == ['local-translation']
        assert services[name]['volumes'] == ['local_translation_models:/model_cache']
    assert set(services['local-translator']['depends_on']) == {'local-model-init'}
    assert {name for name, s in services.items() if not s.get('profiles')} == {
        'init', 'db', 'migrate', 'app', 'worker', 'parser', 'parser-models'}


def test_release_environment_example_names_are_consumed_by_production_compose():
    example = Path('.env.example').read_text()
    compose = Path('compose.example.yaml').read_text()
    documented = set(re.findall(r'^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=', example, re.MULTILINE))
    consumed = set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)', compose))
    assert documented <= consumed, f'Unused deployment settings: {sorted(documented - consumed)}'


def test_one_portable_application_image_with_separate_service_boundaries():
    doc = compose_mode();services = doc['services']
    app = services['app']
    for name in ('worker', 'parser', 'parser-models'):
        assert services[name]['image'] == app['image']
        assert services[name]['build'] == app['build']
        assert 'platform' not in services[name]
    parser, manager = services['parser'], services['parser-models']
    assert parser['environment']['PARSER_ACCELERATOR'] == 'dmr'
    assert parser['networks'] == manager['networks'] == ['parser_model_control', 'model_inference']
    assert doc['networks']['parser_model_control']['internal'] is True
    assert 'parser_model_control' in services['worker']['networks']
    assert parser['volumes'] == ['parser_inputs:/inputs:ro', 'parser_outputs:/outputs', 'parser_models:/model_cache:ro']
    assert manager['volumes'] == ['parser_models:/model_cache']
    assert not any(parser.get(k) or manager.get(k) for k in ('ports', 'secrets', 'models'))
    assert not Path('deployment/images/parser.Dockerfile').exists()
    recipe = Path('deployment/images/app.Dockerfile').read_text()
    assert 'download_parser_models' not in recipe and 'COPY --from=models' not in recipe


def test_active_lock_contains_no_native_frameworks_or_archived_models():
    packages = {row['name'] for row in tomllib.loads(Path('uv.lock').read_text())['package']}
    assert not packages & {'docling', 'torch', 'transformers', 'onnxruntime', 'paddlepaddle', 'paddleocr', 'paddlex', 'opencv-contrib-python'}
    vision = json.loads(Path('deployment/parser-vlm-models.lock.json').read_text())
    assert {model['id'] for model in vision['models']} == {'surya-ocr-2-v1', 'chandra-ocr-2-v1', 'infinity-parser2-pro-v1', 'infinity-parser2-flash-v1'}
    assert not Path('deployment/parser-models.lock.json').exists()
    assert 'archive' in Path('.dockerignore').read_text().splitlines()
