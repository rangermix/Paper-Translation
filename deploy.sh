#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -f compose.yaml ]]; then
  echo 'Create compose.yaml from compose.example.yaml and choose your hardware settings first.' >&2
  exit 1
fi

# Use the selected local instance; pass options such as --env-file or --profile.
compose=(docker compose -f compose.yaml "$@")
"${compose[@]}" build app parser db
"${compose[@]}" up -d --wait
"${compose[@]}" ps
