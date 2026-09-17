# Repository Layout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give documentation, executable source, runtime resources and deployment definitions clear homes without changing product behavior.

**Architecture:** Keep the repository root as the command/build context. Put prose and acceptance planning under `docs/`, executable Python/frontend source under `src/`, and Docker recipes under `deployment/images/`. Separate runtime schemas and frozen seed/reader resources from prose; preserve their content and resolve historical paths without rewriting archived evidence.

**Tech Stack:** Python 3.12, React/TypeScript/Vite, PostgreSQL, Docker Compose, pytest and Playwright.

## 1. Inventory and documentation/deployment checkpoint

- Review every tracked `deployment/` and `images/` file and record its active consumers or archival purpose.
- Move `images/*.Dockerfile` and the test/verifier recipes to `deployment/images/` and update shared Compose entries and the local Compose recipe paths while retaining all selected MLX/environment/volume settings.
- Move the product baseline, milestone specifications/plans, shared contracts and operations prose to `docs/`; move deployment prose to `docs/deployment/`; remove the obsolete design-only dependency checklist and consolidate the duplicate environment template.
- Update maintained Markdown links, command examples and agent entry instructions. Preserve dated agent evidence and frozen artifacts.
- Run Compose configuration resolution and the package checker, inspect the diff, then commit and push this independently working checkpoint.

## 2. Source and runtime-resource checkpoint

- Move the former root application, package, worker and tooling directories under `src/`; move the two executable operations scripts to `src/tools/`.
- Move machine-readable schemas and frozen reference inputs to `res/`; move acceptance planning/tracking contracts to `docs/contracts/` and reference prose to `docs/reference/`.
- Update Python import paths, root/resource resolution, frontend test paths and all Docker COPY/commands consistently. Keep module entrypoint names unchanged.
- Preserve immutable seed manifests and hashes. Resolve their old logical `reference/` paths relative to the new resource root.
- Extend maintained harness path relocation for archived source references. Do not alter archived content or claim its old hashes certify changed source.
- Validate Python collection/imports, schema and frozen-seed checks, parser packaging paths, Docker build inputs, frontend unit/build/browser tests, and the complete dedicated Linux/PostgreSQL suite.
- Obtain an independent review of the final relocation, fix any regressions, then commit and push the verified result.

## 3. Completion

- Document the final directory tree and the reason retained deployment components are required.
- Record exact commands, source commit, output and proof limitations in a unique `.agent/tmp/` run and durable handoff note.
- Confirm the configured branch matches the remote, the worktree is clean, and local Compose semantics are unchanged apart from relocated build paths.
- Stop only this task's temporary preview/database containers. Do not deploy production or call/download models as part of a directory move.
