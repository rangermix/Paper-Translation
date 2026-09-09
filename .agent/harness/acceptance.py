"""Evidence-first acceptance ledger. Never equates specification checks to product tests."""
from __future__ import annotations

if __package__:
    from ._project import ROOT, artifact_path, output_path
else:
    from _project import ROOT, artifact_path, output_path

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid


STATUSES = {"passed", "failed", "blocked", "not_run"}
KINDS = {"specification", "automated", "compose", "browser", "live_provider", "agent_review"}
IGNORED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build", "evidence", "reports", "test-results", "playwright-report", ".cache", ".local-data"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(root=ROOT):
    rows = []
    root = Path(root).resolve()
    excluded = ('.agent/tmp/', '.agent/memory/', '.agent/notes/', '.agent/local-data/',
                'harness/memory/', 'notes/', 'secrets/', '.local-data/')
    paths = []
    # Do not traverse archives, virtual disks or dependency caches just to skip
    # their contents later. The tracked .agent/harness code remains fingerprinted.
    for directory, children, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        children[:] = [name for name in children if name not in IGNORED_PARTS
                       and not (parent / name).is_symlink()
                       and not getattr(parent / name, 'is_junction', lambda: False)()
                       and not ((parent / name).relative_to(root).as_posix().lower() + '/').startswith(excluded)]
        paths.extend(parent / name for name in files)
    for path in sorted(paths):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        lowered=relative.as_posix().lower()
        if (lowered.startswith(excluded)
                or relative.name == "IMPLEMENTATION_STATUS.md" or lowered == "apps/web/work_log.md"):
            continue
        if relative.name == '.env' or (relative.name.startswith('.env.') and relative.name != '.env.example'):
            continue
        if path.is_file() and not path.is_symlink():
            rows.append([relative.as_posix(), digest(path)])
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def catalog(root=ROOT):
    requirements = read_json(root / "contracts/requirements.json")
    gates = read_json(root / "contracts/exit-gates.json")
    packages = read_json(root / "contracts/implementation-backlog.json")
    tests = {test["id"]: {**test, "milestone": req["milestone"]} for req in requirements for test in req["tests"]}
    req_ids = {req["id"] for req in requirements}
    package_ids = {package["id"] for package in packages}
    assert len(requirements) == len(req_ids) == 65, "Requirement registry changed or duplicated"
    assert len(tests) == 130, "Expected 130 distinct acceptance scenarios"
    assert len({gate["id"] for gate in gates}) == len(gates) == 24, "Expected 24 distinct gates"
    assert len(package_ids) == len(packages) == 42, "Expected 42 work packages"
    for gate in gates:
        assert set(gate["requirements"]) <= req_ids, gate["id"]
    graph = {package["id"]: package["depends_on"] for package in packages}
    for package in packages:
        assert set(package["requirements"]) <= req_ids, package["id"]
        assert set(package["depends_on"]) <= package_ids, package["id"]
    visiting, done = set(), set()
    def visit(node):
        assert node not in visiting, "Dependency cycle at " + node
        if node in done:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        done.add(node)
    for node in graph:
        visit(node)
    policy = read_json(root / ".agent/harness/gate-policy.json")
    assert set(policy) == {gate["id"] for gate in gates}, "Gate policy coverage differs"
    prerequisites = read_json(root / ".agent/harness/gate-prerequisites.json")
    assert set(prerequisites) <= set(policy), "Unknown gate prerequisite target"
    assert all(set(values) <= set(tests) for values in prerequisites.values()), "Unknown literal gate prerequisite"
    return requirements, tests, gates, packages


def command_result(argv, timeout=30):
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False)
        return {"argv": argv, "exit_code": result.returncode, "output": redact(result.stdout + result.stderr)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "exit_code": None, "output": redact(str(exc))}


def redact(text):
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED_API_KEY]", text)
    text = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(r'(?i)(["\x27]?(?:api[_-]?key|password|secret|access_token)["\x27]?\s*[:=]\s*)[^\r\n,}]+', r'\1[REDACTED]', text)
    text = re.sub(r"(postgres(?:ql)?(?:\+[A-Za-z0-9_]+)?://[^:\s/]+:)[^@\s]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s?#]+@", r"\1[REDACTED]@", text)
    text = re.sub(r'''(?i)([?&](?:access_token|refresh_token|token|api[_-]?key|password|secret|authorization|auth|key)=)[^&#\s"'<>]+''', r"\1[REDACTED]", text)
    return text


def environment():
    commit = command_result(["git", "rev-parse", "HEAD"])
    dirty = command_result(["git", "status", "--porcelain"])
    return {"os": platform.platform(), "machine": platform.machine(), "python": platform.python_version(), "git_commit": commit["output"].strip() if commit["exit_code"] == 0 else None, "dirty_tree": bool(dirty["output"].strip()), "docker_cli_present": shutil.which("docker") is not None}


def safe_evidence(path, root=ROOT):
    root = Path(root).resolve()
    resolved = artifact_path(path, root)
    if not resolved.is_file():
        raise ValueError("Evidence must be an existing ordinary file inside project: " + str(path))
    return {"path": resolved.relative_to(root).as_posix(), "sha256": digest(resolved), "bytes": resolved.stat().st_size}


def validate_record(record, tests, root=ROOT):
    if record.get("status") not in STATUSES or record.get("kind") not in KINDS:
        raise ValueError("Invalid evidence status/kind")
    if not set(record.get("test_ids", [])) <= set(tests):
        raise ValueError("Unknown AT in evidence")
    if not re.fullmatch(r"[a-f0-9]{64}", record.get("source_tree_sha256", "")):
        raise ValueError("Missing source tree fingerprint")
    for item in record.get("files", []):
        actual = safe_evidence(item["path"], root)
        if actual["sha256"] != item["sha256"]:
            raise ValueError("Changed evidence file: " + item["path"])
    if record["kind"] == "agent_review":
        if not record.get("reviewer_agent") or record.get("reviewer_agent") == record.get("implementation_agent"):
            raise ValueError("An independent reviewer agent is required")
        if not record.get("implementation_agent") or not record.get("findings"):
            raise ValueError("Review needs implementer identity and actual findings")
    if record["status"] == "passed" and record.get("full_scenario"):
        if record["kind"] == "specification":
            raise ValueError("Specification checks cannot complete product scenarios")
        if not record.get("files"):
            raise ValueError("Passed scenarios require tangible evidence")
        if record["kind"] != "agent_review" and record.get("exit_code") != 0:
            raise ValueError("Passed execution requires exit code zero")
    return record


def store_record(record):
    _, tests, _, _ = catalog()
    validate_record(record, tests)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", record["id"])
    path = ROOT / ".agent/tmp/evidence/runs" / (stamp + "-" + safe_id + "-" + uuid.uuid4().hex[:8] + ".json")
    record["recorded_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, record)
    print(path.relative_to(ROOT).as_posix())


def aggregate(tests, gates, records, source_tree, policy, prerequisites=None):
    prerequisites = prerequisites or {}
    current = [r for r in records if r["source_tree_sha256"] == source_tree]
    results = {}
    for test_id, test in tests.items():
        relevant = [r for r in current if test_id in r.get("test_ids", [])]
        full = [r for r in relevant if r.get("full_scenario") and r["kind"] != "specification"]
        # Latest observation in a proof kind controls it; a fixed failure must be rerun.
        latest = {r["kind"]: r for r in full}
        passing = {kind for kind, r in latest.items() if r["status"] == "passed"}
        if any(r["status"] == "failed" for r in latest.values()):
            status = "failed"
        elif passing - {"agent_review"} and (test["mode"] != "mixed" or "agent_review" in passing):
            status = "passed"
        elif any(r["status"] == "blocked" for r in relevant):
            status = "blocked"
        else:
            status = "not_run"
        results[test_id] = {"status": status, "requirement_id": test["requirement_id"], "mode": test["mode"], "proof_kinds": sorted(passing), "supporting_records": [r["id"] for r in relevant], "scenario": test["scenario"]}
    gate_results = []
    for gate in gates:
        members = [key for key, value in results.items() if value["requirement_id"] in gate["requirements"] or key in prerequisites.get(gate['id'], [])]
        states = [results[key]["status"] for key in members]
        kinds = {kind for key in members for kind in results[key]["proof_kinds"]}
        missing = sorted(set(policy[gate["id"]]) - kinds)
        state = "failed" if "failed" in states else "blocked" if "blocked" in states else "passed" if all(s == "passed" for s in states) and not missing else "not_run"
        gate_results.append({"id": gate["id"], "milestone": gate["milestone"], "title": gate["title"], "status": state, "test_ids": members, "missing_proof_kinds": missing, "required_evidence": gate["evidence"]})
    for gate in gate_results:
        if gate["id"] == "M2-G08":
            incomplete = [g["id"] for g in gate_results if g["milestone"] in {"M0", "M1"} and g["status"] != "passed"]
            gate["incomplete_inherited_gates"] = incomplete
            if incomplete and gate["status"] == "passed":
                gate["status"] = "not_run"
    return results, gate_results


def report():
    requirements, tests, gates, packages = catalog()
    source_tree = fingerprint()
    records, rejected = [], []
    for path in sorted((ROOT / ".agent/tmp/evidence/runs").glob("*.json")):
        try:
            records.append(validate_record(read_json(path), tests))
        except (ValueError, KeyError, OSError) as exc:
            rejected.append({"path": path.relative_to(ROOT).as_posix(), "error": str(exc)})
    results, gate_results = aggregate(tests, gates, records, source_tree, read_json(ROOT / ".agent/harness/gate-policy.json"), read_json(ROOT / ".agent/harness/gate-prerequisites.json"))
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "source_tree_sha256": source_tree, "environment": environment(), "counts": {"requirements": len(requirements), "tests": len(tests), "gates": len(gates), "work_packages": len(packages)}, "test_status_counts": dict(Counter(r["status"] for r in results.values())), "gate_status_counts": dict(Counter(g["status"] for g in gate_results)), "tests": results, "gates": gate_results, "rejected_records": rejected, "stale_record_count": sum(r["source_tree_sha256"] != source_tree for r in records), "completion_claim_allowed": not rejected and all(g["status"] == "passed" for g in gate_results)}
    observed_path = ROOT / ".agent/tmp/evidence/observed-scenario-map.json"
    observed = read_json(observed_path).get("tests", []) if observed_path.is_file() else []
    observed_counts = {
        "tests_with_scoped_observations": sum(bool(row.get("observations")) for row in observed),
        "tests_with_historical_literal_coverage_assertion": sum(any(item.get("literal_scenario_covered") is True for item in row.get("observations", [])) for row in observed),
        "tests_without_mapping": len(tests) - sum(bool(row.get("observations")) for row in observed),
    }
    result["historical_observations"] = {"counts": observed_counts, "path": ".agent/tmp/evidence/observed-scenario-map.json",
        "meaning": "Scoped behavior observations from implementation and independent agents; never automatically promoted to current source-bound gate passes."}
    write_json(ROOT / ".agent/tmp/evidence/acceptance-report.json", result)
    lines = ["# Implementation acceptance status", "", "Generated from actual execution evidence by `.agent/harness/acceptance.py report`.", "", f"Source tree: `{source_tree}`. Git: `{result['environment']['git_commit']}`; dirty: {result['environment']['dirty_tree']}.", "", "Design/prototype checks and file presence do not prove product completion. A stale result never completes the current tree.", "", f"AT: {result['test_status_counts']}. Gates: {result['gate_status_counts']}. Stale records: {result['stale_record_count']}.", "", "| Gate | Status | Missing proof kinds |", "|---|---|---|"]
    lines += [f"| {gate['id']} {gate['title']} | {gate['status']} | {', '.join(gate['missing_proof_kinds']) or '-'} |" for gate in gate_results]
    lines += ["", "The table above answers whether the current source has all required registered proof. `not_run` does not mean that the feature is absent: source changes invalidate earlier certificates, and partial behavior checks cannot complete a literal scenario.", "",
        f"Historical scoped observations: {observed_counts['tests_with_scoped_observations']}/{len(tests)} scenarios mapped; {observed_counts['tests_with_historical_literal_coverage_assertion']} have at least one agent's literal-coverage assertion for its recorded version. These assertions do not change the gate table.", "",
        "Read the [scenario observation map](tmp/evidence/observed-scenario-map.json) for commands, evidence paths, exact scope and missing behavior. Real Provider execution remains unauthorized; authored M0 fixtures and simulated Provider responses do not replace real parsed-paper or translation review.", "",
        "Details and current certificates: [acceptance-report.json](tmp/evidence/acceptance-report.json).", "", "File-based handoff: [memory/current.md](memory/current.md).", "", "Completion claim allowed: " + str(result["completion_claim_allowed"]).lower() + "."]
    (ROOT / ".agent/IMPLEMENTATION_STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ["test_status_counts", "gate_status_counts", "stale_record_count", "completion_claim_allowed"]}, ensure_ascii=False))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["inventory", "probe", "fingerprint", "report", "gates"]:
        sub.add_parser(name)
    run = sub.add_parser("run")
    run.add_argument("--id", required=True)
    run.add_argument("--kind", choices=sorted(KINDS - {"agent_review"}), required=True)
    run.add_argument("--tests", nargs="*", default=[])
    run.add_argument("--full-scenario", action="store_true")
    run.add_argument("--timeout", type=int, default=1800)
    run.add_argument("argv", nargs=argparse.REMAINDER)
    blocked = sub.add_parser("blocked")
    blocked.add_argument("--id", required=True)
    blocked.add_argument("--tests", nargs="+", required=True)
    blocked.add_argument("--reason", required=True)
    review = sub.add_parser("review")
    review.add_argument("path")
    args = parser.parse_args(argv)
    if args.command == "fingerprint":
        print(fingerprint()); return 0
    if args.command in {"report", "gates"}:
        result = report()
        return 0 if args.command == "report" or result["completion_claim_allowed"] else 1
    if args.command == "inventory":
        reqs, tests, gates, packages = catalog()
        inventory = {"scope": "code presence only, never implementation completion", "counts": [len(reqs), len(tests), len(gates), len(packages)], "work_packages": [{"id": package["id"], "depends_on": package["depends_on"], "outputs": [{"path": path, "exists": artifact_path(path).exists()} for path in package["outputs"]]} for package in packages]}
        write_json(ROOT / ".agent/tmp/evidence/inventory.json", inventory)
        print(json.dumps({"requirements": len(reqs), "tests": len(tests), "gates": len(gates), "work_packages": len(packages), "mixed_tests": sum(t["mode"] == "mixed" for t in tests.values())})); return 0
    if args.command == "probe":
        probe = {"environment": environment(), "docker_version": command_result(["docker", "version", "--format", "{{json .}}"]), "compose_version": command_result(["docker", "compose", "version", "--short"]), "note": "CLI/engine discovery only; this does not prove production build or cold start"}
        write_json(ROOT / ".agent/tmp/evidence/environment-probe.json", probe)
        print(json.dumps(probe, ensure_ascii=False)); return 0
    if args.command == "blocked":
        store_record({"id": args.id, "kind": "automated", "status": "blocked", "test_ids": args.tests, "full_scenario": False, "reason": args.reason, "source_tree_sha256": fingerprint(), "environment": environment(), "files": []}); return 0
    if args.command == "review":
        record = read_json(args.path)
        if record["source_tree_sha256"] != fingerprint():
            raise ValueError("Review is stale; inspect the current tree before accepting")
        record.update({"kind": "agent_review", "full_scenario": True, "files": [safe_evidence(p) for p in record.pop("evidence_paths", [])]})
        store_record(record); return 0
    if args.command == "run":
        command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        if not command:
            raise ValueError("An executable argument list is required after --")
        if args.kind == "specification" and args.full_scenario:
            raise ValueError("Static/specification checks cannot complete product scenarios")
        if any(re.search(r"(?i)\bsk-|bearer |password=|api_key=", item) for item in command):
            raise ValueError("Do not place secrets in command arguments")
        before, env, started = fingerprint(), environment(), time.monotonic()
        execution = command_result(command, args.timeout)
        duration = time.monotonic() - started
        log_path = ROOT / ".agent/tmp/evidence/logs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8] + ".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(execution.pop("output"), encoding="utf-8")
        changed = before != fingerprint()
        record = {"id": args.id, "kind": args.kind, "test_ids": args.tests, "full_scenario": args.full_scenario, "status": "passed" if execution["exit_code"] == 0 and not changed else "failed", "source_tree_sha256": before, "source_changed_during_execution": changed, "environment": env, "duration_seconds": round(duration, 3), "files": [safe_evidence(log_path.relative_to(ROOT))], **execution}
        store_record(record)
        print(json.dumps({"status": record["status"], "exit_code": record["exit_code"], "source_changed_during_execution": changed, "duration_seconds": record["duration_seconds"]}))
        return 0 if record["status"] == "passed" else 1
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, AssertionError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
