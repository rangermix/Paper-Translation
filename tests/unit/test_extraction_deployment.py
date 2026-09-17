"""Static deployment contracts; these do not certify Docker or real inference."""
import json
from pathlib import Path
import re
import tomllib

import pytest
import yaml


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor('!reset', lambda loader, node: None)


def test_offline_acceptance_harness_mount_contains_the_restore_runner():
    compose_path = Path('deployment/compose.acceptance-offline.yaml')
    doc = yaml.safe_load(compose_path.read_text())
    for service in ('app', 'maintenance'):
        mounts = [entry.split(':') for entry in doc['services'][service]['volumes']]
        source, _, mode = next(entry for entry in mounts if entry[1] == '/harness')
        assert mode == 'ro'
        assert (compose_path.parent / source / 'offline_compose_roundtrip.py').is_file()


def test_release_environment_example_names_are_consumed_by_production_compose():
    example = Path('.env.example').read_text()
    compose = Path('deployment/compose.production.yaml').read_text()
    documented = set(re.findall(r'^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=', example, re.MULTILINE))
    consumed = set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)', compose))
    assert documented <= consumed, f'Unused deployment settings: {sorted(documented - consumed)}'


def test_cpu_and_cuda_keep_parser_isolation_and_one_unified_image_recipe():
    base = yaml.safe_load(Path('deployment/compose.production.yaml').read_text())
    gpu = yaml.safe_load(Path('deployment/compose.cuda.yaml').read_text())['services']['parser']
    assert base['services']['parser']['network_mode'] == 'none'
    assert 'network_mode' not in gpu and 'networks' not in gpu
    assert gpu['build']['args']['PARSER_FLAVOR'] == 'cuda'
    assert gpu['deploy']['resources']['reservations']['devices'] == [
        {'driver': 'nvidia', 'count': 1, 'capabilities': ['gpu']}]
    recipe = Path('deployment/images/parser.Dockerfile').read_text()
    assert 'FROM dependencies-${PARSER_FLAVOR} AS dependencies' in recipe
    assert '/app/.venv-paddle' in recipe


def test_mlx_is_compose_managed_and_does_not_mount_host_credentials():
    doc = yaml.load(Path('deployment/compose.mlx.yaml').read_text(), Loader=ComposeLoader)
    parser = doc['services']['parser']
    assert parser['models'] == ['paddle_extraction']
    assert parser['network_mode'] is None
    assert parser['networks'] == ['model_inference']
    assert not set(parser) & {'ports', 'volumes', 'secrets', 'command'}
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


def test_export_refuses_overwrite_and_verifies_before_copy(tmp_path, monkeypatch):
    from tools.export_parser_model import export_model
    root = tmp_path / 'weights'; root.mkdir()
    (root / 'paddle').mkdir(); (root / 'paddle' / 'weight').write_bytes(b'locked')
    model = {'repo_id': 'PaddlePaddle/PaddleOCR-VL-1.6', 'local_directory': 'paddle',
        'revision': 'fixed', 'files': [{'path': 'weight'}]}
    calls = []
    monkeypatch.setattr('tools.export_parser_model.verify_models', lambda path: calls.append(path) or {'repositories': [model]})
    target = tmp_path / 'export'
    assert export_model(root, target) == 'fixed'
    assert calls == [root]
    assert (target / 'weight').read_bytes() == b'locked'
    with pytest.raises(ValueError, match='MODEL_EXPORT_DESTINATION_EXISTS'):
        export_model(root, target)
