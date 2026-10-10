#!/usr/bin/env bash
# Runs on the server (called by the GitHub Action). Safe to run repeatedly.
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch origin main
git reset --hard origin/main

[ -d venv ] || python3 -m venv venv
./venv/bin/pip install --quiet -r requirements.txt

./venv/bin/python manage.py migrate --noinput
./venv/bin/python manage.py collectstatic --noinput

sudo systemctl restart wiadspot
sudo systemctl is-active --quiet wiadspot
echo "Deployed $(git rev-parse --short HEAD)"
