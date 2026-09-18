"""Compose harness configuration is isolated without launching containers."""
import copy
import json

import pytest

from harness import verify_compose
from harness._project import ROOT, artifact_path


def canonical_config():
    base = {'user': '10001:10001', 'read_only': True, 'cap_drop': ['ALL'],
            'volumes': [], 'environment': {}, 'command': ['python', '-m', 'workers.main']}
    services = {name: copy.deepcopy(base) for name in ('init', 'db', 'migrate', 'app', 'worker', 'parser')}
    services['init']['user'] = '0:0'
    for name in ('init', 'app', 'worker'):
        services[name]['volumes'] = [{'type': 'volume', 'source': 'provider_config', 'target': '/provider_config',
                                     'read_only': name == 'worker'}]
    services['app']['ports'] = [{'target': 8080, 'host_ip': '127.0.0.1', 'published': '8080'}]
    services['parser'].update(network_mode='none', mem_limit=16 * 1024**3, pids_limit=256, cpus=4,
        volumes=[{'type': 'volume', 'source': 'parser_inputs', 'target': '/inputs', 'read_only': True},
                 {'type': 'volume', 'source': 'parser_outputs', 'target': '/outputs'}])
    return {'services': services}


def test_verifier_accepts_settings_managed_default_without_key_mounts():
    result = verify_compose.inspect_config(canonical_config())
    assert result['services'] == sorted(canonical_config()['services'])


@pytest.mark.parametrize('mutation', [
    lambda config: config.update(secrets={'provider_key': {'file': '/private/key'}}),
    lambda config: config['services']['worker'].update(secrets=[{'source': 'provider_key'}]),
    lambda config: config['services']['worker']['environment'].update(PROVIDER_KEY_FILE='/run/secrets/provider_key'),
    lambda config: config['services']['app']['environment'].update(PROVIDER_PROFILE_FILE='/config/provider-profile.json'),
    lambda config: config['services']['app']['volumes'].append(
        {'type': 'bind', 'source': '/private/profile', 'target': '/config/provider-profile.json', 'read_only': True}),
    lambda config: config['services']['worker']['volumes'][0].update(read_only=False),
])
def test_verifier_rejects_default_external_provider_inputs_or_writable_worker_config(mutation):
    config = canonical_config()
    mutation(config)
    with pytest.raises(AssertionError):
        verify_compose.inspect_config(config)


def test_profiled_checks_are_valid_but_never_default_or_connected_to_production():
    config = canonical_config()
    config['services']['checks'] = {'profiles': ['checks'], 'network_mode': 'none',
        'user': '10001:10001', 'read_only': True, 'cap_drop': ['ALL'], 'command': ['python', 'src/tools/check_package.py']}
    verify_compose.inspect_config(config)
    for mutation in (lambda service: service.pop('profiles'),
                     lambda service: service.update(depends_on={'db': {}}),
                     lambda service: service.update(volumes=[{'type': 'volume', 'source': 'data', 'target': '/data'}])):
        changed = copy.deepcopy(config)
        mutation(changed['services']['checks'])
        with pytest.raises(AssertionError):
            verify_compose.inspect_config(changed)


def test_optional_test_database_can_publish_only_a_loopback_port():
    config = canonical_config()
    config['services']['test-db'] = {'profiles': ['tests'], 'networks': {'test_backend': {}},
        'ports': [{'target': 5432, 'published': '55439', 'host_ip': '127.0.0.1'}]}
    verify_compose.inspect_config(config)
    config['services']['test-db']['ports'][0]['host_ip'] = '0.0.0.0'
    with pytest.raises(AssertionError):
        verify_compose.inspect_config(config)


def mlx_config():
    config = canonical_config()
    parser = config['services']['parser']
    parser.pop('network_mode')
    parser.update(networks={'model_inference': {}}, models={'paddle_extraction': {}})
    parser['environment'].update(PARSER_ACCELERATOR='mlx', PADDLE_MLX_MODEL_ID='sha256:' + 'a' * 64,
        PARSER_MLX_VERIFIED_MODEL_ID='sha256:' + 'a' * 64)
    config['models'] = {'paddle_extraction': {'model': 'docker.io/local/paddle-fixture:fixed'}}
    return config


def test_mlx_verifier_requires_only_model_network_and_records_binding():
    config = mlx_config()
    result = verify_compose.inspect_config(config)
    assert result['parser_accelerator'] == 'mlx'
    assert result['mlx_model_binding']['model_id'] == 'sha256:' + 'a' * 64
    for mutation in (lambda p: p['networks'].update(backend={}),
                     lambda p: p['environment'].update(PARSER_MLX_VERIFIED_MODEL_ID='sha256:' + 'b' * 64),
                     lambda p: p['environment'].update(PADDLE_MLX_MODEL_ID='unverified-alias'),
                     lambda p: p.pop('models')):
        changed = copy.deepcopy(config)
        mutation(changed['services']['parser'])
        with pytest.raises(AssertionError):
            verify_compose.inspect_config(changed)
    config.pop('models')
    with pytest.raises(AssertionError):
        verify_compose.inspect_config(config)


@pytest.mark.parametrize('accelerator', ['cpu', 'cuda'])
def test_cpu_and_cuda_cannot_gain_a_parser_network(accelerator):
    config = canonical_config()
    config['services']['parser']['environment']['PARSER_ACCELERATOR'] = accelerator
    verify_compose.inspect_config(config)
    config['services']['parser']['network_mode'] = 'host'
    with pytest.raises(AssertionError):
        verify_compose.inspect_config(config)


def test_running_verifier_requires_explicit_project_before_any_command(monkeypatch):
    monkeypatch.setattr('sys.argv', ['verify_compose.py', '--running'])
    monkeypatch.setattr(verify_compose, 'command', lambda _: pytest.fail('Must not inspect an implicit live project'))
    with pytest.raises(SystemExit) as error:
        verify_compose.main()
    assert error.value.code == 2


def test_running_verifier_preserves_explicit_files_environment_and_project(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr('sys.argv', ['verify_compose.py', '--running', '--file', 'selected.yaml',
        '--file', 'override.json', '--env-file', 'selected.env', '--project-name', 'disposable-review'])
    monkeypatch.setattr(verify_compose, 'command', lambda argv: calls.append(argv) or json.dumps(canonical_config()))
    monkeypatch.setattr(verify_compose, 'inspect_running', lambda argv, config: calls.append(argv) or {})
    verify_compose.main()
    expected = ['docker', 'compose', '-f', 'selected.yaml', '-f', 'override.json',
        '--env-file', 'selected.env', '-p', 'disposable-review']
    assert calls == [expected + ['--profile', '*', 'config', '--format', 'json'], expected]
    assert json.loads(capsys.readouterr().out)['scope'] == 'runtime inspection'


def test_mlx_verifier_reads_yaml_when_json_omits_model_declarations(monkeypatch, capsys):
    config = mlx_config()
    partial = copy.deepcopy(config)
    partial.pop('models')
    responses = iter([json.dumps(partial), json.dumps(config)])
    calls = []
    monkeypatch.setattr('sys.argv', ['verify_compose.py', '--file', 'mlx.yaml'])
    monkeypatch.setattr(verify_compose, 'command', lambda argv: calls.append(argv) or next(responses))
    verify_compose.main()
    assert calls[0][-3:] == ['config', '--format', 'json']
    assert calls[1][-1] == 'config'
    report = json.loads(capsys.readouterr().out)
    assert report['configuration']['mlx_model_binding']['declarations'] == config['models']


def test_offline_override_uses_each_run_directory_and_preserves_internal_networks(tmp_path):
    from harness._compose import write_offline_override
    for name in ('first', 'second'):
        run = tmp_path / name
        run.mkdir()
        path = write_offline_override(run)
        config = json.loads(path.read_text())
        assert path.parent == run
        assert all(config['networks'][network]['internal'] for network in ('backend', 'http', 'provider_egress'))
        assert config['services']['db']['image'].startswith('${DATABASE_IMAGE:')
        for service in ('app', 'maintenance'):
            mounts = {item['target']: item for item in config['services'][service]['volumes']}
            assert mounts['/harness']['source'] == (ROOT / '.agent/harness').as_posix()
            assert mounts['/harness']['read_only'] is True
            assert mounts['/evidence']['source'] == run.as_posix()
        assert 'secrets' not in config
        with pytest.raises(FileExistsError):
            write_offline_override(run)


def test_explicit_provider_override_sets_profile_and_worker_key_without_reading_files(tmp_path):
    from harness._compose import provider_override
    profile, key = tmp_path / 'approved-public.json', tmp_path / 'not-read.key'
    override = provider_override(profile, key=key)
    assert not profile.exists() and not key.exists()
    app, worker = (override['services'][name] for name in ('app', 'worker'))
    assert app['environment'] == {'PROVIDER_PROFILE_FILE': '/config/provider-profile.json'}
    assert 'secrets' not in app
    assert worker['environment']['PROVIDER_KEY_FILE'] == '/run/secrets/provider_key'
    assert worker['secrets'] == ['provider_key']
    assert override['secrets'] == {'provider_key': {'file': key.as_posix()}}
    for service in (app, worker):
        assert service['volumes'] == [{'type': 'bind', 'source': profile.as_posix(),
            'target': '/config/provider-profile.json', 'read_only': True}]
    offline = provider_override(profile)
    assert 'secrets' not in offline
    assert 'PROVIDER_KEY_FILE' not in offline['services']['worker']['environment']


def test_deleted_overlay_paths_are_not_aliased_to_a_different_compose_project():
    contract = json.loads((ROOT / '.agent/relocation.json').read_text())
    retired = contract['retired_compose_inputs']
    assert 'deployment/compose.test.yaml' in retired
    assert 'tests/compose.offline.yaml' in retired
    for old in retired:
        assert old not in contract['files']
        assert artifact_path(old) == ROOT / old
