#!/bin/sh
set -e

python scripts/wait_for_db.py
python manage.py migrate --noinput

exec "$@"
