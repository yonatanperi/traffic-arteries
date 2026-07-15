#!/usr/bin/env bash
# Render build script. manage.py lives under backend/.
set -o errexit

pip install -r backend/requirements.txt
python backend/manage.py collectstatic --noinput
python backend/manage.py migrate
