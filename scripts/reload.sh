#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  echo "Missing .env file. Copy .env.example and fill in production secrets before deploying." >&2
  exit 1
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"

echo ">>> Fetching latest commits for ${current_branch}"
git fetch --all --prune
git pull --ff-only origin "${current_branch}"

echo ">>> Pulling container updates"
docker compose pull

echo ">>> Building web image"
docker compose build web

echo ">>> Applying containers"
docker compose up -d --remove-orphans

echo ">>> Current container status"
docker compose ps
