"""Verify the real Compose configuration and (with --running) its actual containers.

Configuration-only mode is prerequisite evidence, not a cold-start AT.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


DEFAULT_SERVICES = {"init", "db", "migrate", "app", "worker", "parser"}
PROFILED_SERVICES = {"maintenance": "maintenance", "local-model-init": "local-translation",
    "local-translator": "local-translation", "model-export": "model-tools",
    "tests": "tests", "test-db": "tests", "checks": "checks"}


def command(argv):
    result = subprocess.run(argv, cwd=ROOT, env={**os.environ, "COMPOSE_PROFILES": ""},
        capture_output=True, text=True, check=True)
    return result.stdout


def inspect_config(config):
    services = config["services"]
    assert DEFAULT_SERVICES <= set(services) <= DEFAULT_SERVICES | set(PROFILED_SERVICES)
    assert {name for name, service in services.items() if not service.get("profiles")} == DEFAULT_SERVICES
    for name, profile in PROFILED_SERVICES.items():
        if name in services:
            assert services[name].get("profiles") == [profile], name
    assert not config.get("secrets"), "The canonical template must use settings-managed credentials"
    published = {name for name, service in services.items() if service.get("ports")}
    assert published <= {"app", "test-db"}, "Only app and the optional test database publish ports"
    if "test-db" in published:
        assert all(port.get("host_ip") == "127.0.0.1" and port["target"] == 5432
            for port in services["test-db"]["ports"]), "Test database ports must bind loopback"
    ports = services["app"]["ports"]
    assert len(ports) == 1 and ports[0]["target"] == 8080
    assert ports[0].get("host_ip") == "127.0.0.1", "Default deployment must bind loopback"
    parser = services["parser"]
    accelerator = parser.get('environment', {}).get('PARSER_ACCELERATOR', 'cpu')
    assert accelerator in {'cpu', 'cuda', 'mlx'}, accelerator
    model_binding = None
    if accelerator == 'mlx':
        assert not parser.get('network_mode') and set(parser.get('networks', {})) == {'model_inference'}
        model_id = parser['environment'].get('PADDLE_MLX_MODEL_ID', '')
        assert re.fullmatch(r'sha256:[a-f0-9]{64}', model_id), 'MLX requires its actual immutable model ID'
        verified_id = parser['environment'].get('PARSER_MLX_VERIFIED_MODEL_ID', '')
        assert not verified_id or verified_id == model_id, 'MLX verification binding differs from the selected model'
        declared = parser.get('models', {})
        assert declared and set(declared) <= set(config.get('models', {})), 'Resolved YAML model declarations are required'
        models = {name: config['models'][name] for name in declared}
        assert all(model.get('model') for model in models.values()), 'Every parser model needs a declared reference'
        model_binding = {'model_id': model_id, 'verification_model_id': verified_id or None,
                         'declarations': models, 'scope': 'configuration binding; no inference performed'}
    else:
        assert parser.get('network_mode') == 'none' and not parser.get('networks')
    assert not parser.get("secrets")
    assert all("database" not in key.lower() and "provider" not in key.lower() for key in parser.get("environment", {}))
    assert {volume["target"] for volume in parser["volumes"]} == {"/inputs", "/outputs"}
    assert next(volume for volume in parser["volumes"] if volume["target"] == "/inputs")["read_only"]
    for name, service in services.items():
        assert all("docker.sock" not in str(volume) for volume in service.get("volumes", []))
        assert not service.get("privileged", False)
        assert not any(word in " ".join(service.get("command") or []).lower() for word in ["pip install", "npm install", "apt-get"])
        if name not in {"init", "local-model-init", "tests", "test-db"}:
            assert service["user"].split(":")[0] not in {"root", "0"}, name
            assert service["read_only"], name
            assert "ALL" in service["cap_drop"], name
        assert not service.get("secrets"), name
        assert not {"PROVIDER_KEY_FILE", "PROVIDER_PROFILE_FILE"} & set(service.get("environment", {})), name
        assert not any(volume["target"].startswith("/run/secrets/") or
            volume["target"] in {"/config/provider-profile.json", "/config/provider.json"}
            for volume in service.get("volumes", [])), name
    for name, service in services.items():
        mounts = [volume for volume in service.get("volumes", []) if volume["target"] == "/provider_config"]
        if name in {"init", "app", "worker"}:
            assert len(mounts) == 1 and mounts[0]["type"] == "volume", name
            assert bool(mounts[0].get("read_only")) == (name == "worker"), name
        else:
            assert not mounts, name
    if "checks" in services:
        checks = services["checks"]
        assert checks["network_mode"] == "none" and not checks.get("depends_on")
        assert not checks.get("volumes"), "Repository checks must not mount application state"
    production_volumes = {volume["source"] for name in DEFAULT_SERVICES
        for volume in services[name].get("volumes", []) if volume.get("type") == "volume"}
    production_networks = {network for name in DEFAULT_SERVICES for network in services[name].get("networks", {})}
    for name in ("tests", "test-db"):
        if name in services:
            assert not set(services[name].get("networks", {})) & production_networks, name
            assert not any(volume.get("type") == "volume" and volume["source"] in production_volumes
                for volume in services[name].get("volumes", [])), name
            assert set(services[name].get("depends_on", {})) <= {"test-db"}, name
    assert 0 < int(parser["mem_limit"]) <= 16 * 1024**3
    assert 0 < int(parser["pids_limit"]) <= 256
    assert 0 < float(parser["cpus"]) <= 4
    return {"services": sorted(services), "published_ports": ports, "parser_isolation": "configuration asserted",
            "parser_accelerator": accelerator, "mlx_model_binding": model_binding,
            "default_services": sorted(DEFAULT_SERVICES),
            "optional_profiles": {name: PROFILED_SERVICES[name] for name in sorted(set(services) - DEFAULT_SERVICES)},
            "provider_config": "init/app RW, worker RO; other services have no mount"}


def inspect_running(compose, config):
    results = {}
    for name in ["app", "worker", "parser", "db"]:
        ids = command(compose + ["ps", "-q", name]).split()
        assert len(ids) == 1, "Expected one running " + name
        info = json.loads(command(["docker", "inspect", ids[0]]))[0]
        assert info["State"]["Running"], name
        assert info["State"]["Health"]["Status"] == "healthy", name
        assert info["HostConfig"]["ReadonlyRootfs"], name
        assert info["Config"]["User"].split(":")[0] not in {"", "root", "0"}, name
        assert not any(mount["Destination"].startswith('/run/secrets/') or
            mount["Destination"] in {'/config/provider-profile.json', '/config/provider.json'}
            for mount in info["Mounts"]), name
        if name == "parser":
            expected = config['services']['parser'].get('environment', {})
            observed = dict(item.split('=', 1) for item in info['Config']['Env'])
            accelerator = expected.get('PARSER_ACCELERATOR', 'cpu')
            assert observed.get('PARSER_ACCELERATOR', 'cpu') == accelerator
            if accelerator == 'mlx':
                network = config['networks']['model_inference']['name']
                assert set(info['NetworkSettings']['Networks']) == {network}
                for key in ('PADDLE_MLX_MODEL_ID', 'PARSER_MLX_VERIFIED_MODEL_ID'):
                    assert observed.get(key, '') == expected.get(key, ''), key
            else:
                assert info["HostConfig"]["NetworkMode"] == "none"
            assert not any("SECRET" in env or "PROVIDER" in env or "DATABASE" in env for env in info["Config"]["Env"])
            assert not any("docker.sock" in mount["Destination"] for mount in info["Mounts"])
            assert {mount['Destination'] for mount in info['Mounts'] if mount['Type'] != 'tmpfs'} == {'/inputs', '/outputs'}
        if name != "app":
            assert not any(info["HostConfig"]["PortBindings"].values()), name
        provider_mounts = [mount for mount in info["Mounts"] if mount["Destination"] == "/provider_config"]
        if name in {"app", "worker"}:
            assert len(provider_mounts) == 1 and provider_mounts[0]["Type"] == "volume", name
            assert provider_mounts[0]["RW"] == (name == "app"), name
            metadata = json.loads(command(["docker", "exec", ids[0], "python", "-c",
                "import json,os,stat; s=os.stat('/provider_config'); print(json.dumps({'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode))}))"]))
            assert metadata == {"uid": 10001, "gid": 10001, "mode": "0o700"}, metadata
        else:
            assert not provider_mounts, name
        results[name] = {"image_id": info["Image"], "healthy": True, "user": info["Config"]["User"], "read_only_rootfs": True, "network_mode": info["HostConfig"]["NetworkMode"]}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--running", action="store_true")
    parser.add_argument("--file", type=Path, action="append", help="Compose input; repeat for explicit overrides (default: compose.example.yaml).")
    parser.add_argument("--project-name", help="Explicit project required for --running; never inferred from a local checkout.")
    parser.add_argument("--env-file", type=Path, action="append", help="Explicit Compose interpolation file; repeat as needed.")
    args = parser.parse_args()
    if args.running and not args.project_name:
        parser.error("--running requires an explicit --project-name")
    compose = ["docker", "compose"]
    for path in args.file or [Path('compose.example.yaml')]:
        compose += ['-f', str(path)]
    for path in args.env_file or []:
        compose += ['--env-file', str(path)]
    if args.project_name:
        compose += ['-p', args.project_name]
    config = json.loads(command(compose + ["--profile", "*", "config", "--format", "json"]))
    if config['services']['parser'].get('environment', {}).get('PARSER_ACCELERATOR') == 'mlx':
        # Compose's JSON output can omit top-level model declarations.
        import yaml
        resolved = yaml.safe_load(command(compose + ["--profile", "*", "config"]))
        config['models'] = resolved.get('models', {})
        config['services']['parser']['models'] = resolved['services']['parser'].get('models', {})
    result = {"scope": "runtime inspection" if args.running else "configuration only", "configuration": inspect_config(config)}
    if args.running:
        result["containers"] = inspect_running(compose, config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
