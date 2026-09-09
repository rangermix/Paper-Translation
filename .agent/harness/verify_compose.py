"""Verify the real Compose configuration and (with --running) its actual containers.

Configuration-only mode is prerequisite evidence, not a cold-start AT.
"""

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path
import argparse
import json
from pathlib import Path
import subprocess


COMPOSE = ["docker", "compose", "-f", "deployment/compose.production.yaml"]


def command(argv):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout


def inspect_config(config):
    services = config["services"]
    assert set(services) == {"init", "db", "migrate", "app", "worker", "parser", "maintenance"}
    assert [name for name, service in services.items() if service.get("ports")] == ["app"], "Only app publishes a port"
    ports = services["app"]["ports"]
    assert len(ports) == 1 and ports[0]["target"] == 8080
    assert ports[0].get("host_ip") == "127.0.0.1", "Default deployment must bind loopback"
    parser = services["parser"]
    assert parser["network_mode"] == "none"
    assert not parser.get("secrets")
    assert all("database" not in key.lower() and "provider" not in key.lower() for key in parser.get("environment", {}))
    assert {volume["target"] for volume in parser["volumes"]} == {"/inputs", "/outputs"}
    assert next(volume for volume in parser["volumes"] if volume["target"] == "/inputs")["read_only"]
    for name, service in services.items():
        assert all("docker.sock" not in str(volume) for volume in service.get("volumes", []))
        assert not service.get("privileged", False)
        assert not any(word in " ".join(service.get("command") or []).lower() for word in ["pip install", "npm install", "apt-get"])
        if name not in {"init"}:
            assert service["user"].split(":")[0] not in {"root", "0"}, name
            assert service["read_only"], name
            assert "ALL" in service["cap_drop"], name
        if name != "worker":
            assert not service.get("secrets"), name
    assert [secret["source"] for secret in services["worker"]["secrets"]] == ["provider_key"]
    for name, service in services.items():
        mounts = [volume for volume in service.get("volumes", []) if volume["target"] == "/provider_config"]
        if name in {"init", "app", "worker"}:
            assert len(mounts) == 1 and mounts[0]["type"] == "volume", name
            assert bool(mounts[0].get("read_only")) == (name == "worker"), name
        else:
            assert not mounts, name
    assert int(parser["mem_limit"]) <= 4 * 1024**3 and int(parser["pids_limit"]) <= 128
    return {"services": sorted(services), "published_ports": ports, "parser_isolation": "configuration asserted",
            "provider_config": "init/app RW, worker RO; other services have no mount"}


def inspect_running():
    results = {}
    for name in ["app", "worker", "parser", "db"]:
        ids = command(COMPOSE + ["ps", "-q", name]).split()
        assert len(ids) == 1, "Expected one running " + name
        info = json.loads(command(["docker", "inspect", ids[0]]))[0]
        assert info["State"]["Running"], name
        assert info["State"]["Health"]["Status"] == "healthy", name
        assert info["HostConfig"]["ReadonlyRootfs"], name
        assert info["Config"]["User"].split(":")[0] not in {"", "root", "0"}, name
        if name == "parser":
            assert info["HostConfig"]["NetworkMode"] == "none"
            assert not any("SECRET" in env or "PROVIDER" in env or "DATABASE" in env for env in info["Config"]["Env"])
            assert not any("docker.sock" in mount["Destination"] for mount in info["Mounts"])
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
    args = parser.parse_args()
    result = {"scope": "runtime inspection" if args.running else "configuration only", "configuration": inspect_config(json.loads(command(COMPOSE + ["--profile", "maintenance", "config", "--format", "json"])))}
    if args.running:
        result["containers"] = inspect_running()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
