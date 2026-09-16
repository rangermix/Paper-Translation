#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# Pass extra Compose options, such as --env-file or additional -f files.
compose=(docker compose -f deployment/compose.production.yaml "$@")
"${compose[@]}" build app parser db
"${compose[@]}" up -d --wait
"${compose[@]}" ps
