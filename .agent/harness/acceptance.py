"""Evidence-first acceptance ledger. Never equates specification checks to product tests."""
from __future__ import annotations

if __package__:
    from ._project import ROOT, artifact_path
else:
    from _project import ROOT, artifact_path

import argparse
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
                'harness/memory/', 'notes/', 'secrets/', 'provider_config/', '.local-data/', '.vscode/')
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
                or relative.name == "IMPLEMENTATION_STATUS.md" or lowered in {"apps/web/work_log.md", "src/apps/web/work_log.md", "compose.yaml"}):
            continue
        if lowered.startswith('deployment/provider_key.'):
            continue
        if relative.name == '.env' or (relative.name.startswith('.env.') and relative.name != '.env.example'):
            continue
        if path.is_file() and not path.is_symlink():
            rows.append([relative.as_posix(), digest(path)])
    return hashlib.sha256(json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


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


def validate_record(record, root=ROOT):
    if record.get("status") not in STATUSES or record.get("kind") not in KINDS:
        raise ValueError("Invalid evidence status/kind")
    test_ids = record.get("test_ids", [])
    if not isinstance(test_ids, list) or any(not isinstance(value, str) or not value.strip() for value in test_ids):
        raise ValueError("Test IDs must be a list of nonempty descriptive strings")
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
    validate_record(record, root=ROOT)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", record["id"])
    path = ROOT / ".agent/tmp/evidence/runs" / (stamp + "-" + safe_id + "-" + uuid.uuid4().hex[:8] + ".json")
    record["recorded_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, record)
    print(path.relative_to(ROOT).as_posix())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["probe", "fingerprint"]:
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
