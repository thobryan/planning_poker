#!/usr/bin/env bash
set -o errexit
set -o pipefail
set -o nounset

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
