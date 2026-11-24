#!/usr/bin/env bash
# Deploy the latest code from GitHub. Run on the server as the `attendpro` user:
#     sudo -iu attendpro /srv/attendpro/app/deploy/update.sh
# A database backup is taken first, so a bad migration can be rolled back.
set -euo pipefail

APP=/srv/attendpro/app
PY=/srv/attendpro/venv/bin/python
PIP=/srv/attendpro/venv/bin/pip
cd "$APP"

echo "→ Backing up the database"
./deploy/backup.sh

echo "→ Fetching the latest code"
git pull --ff-only

echo "→ Installing packages"
$PIP install -q -r requirements.txt

echo "→ Face models for selfie checks (downloaded once, about 39 MB)"
$PY manage.py get_face_models || echo "⚠ Face models could not be downloaded; selfies are kept but not compared"

echo "→ Updating the database"
$PY manage.py migrate --noinput

echo "→ Collecting static files"
$PY manage.py collectstatic --noinput -v 0

echo "→ Checking settings"
$PY manage.py check --deploy --fail-level ERROR

echo "→ Restarting AttendPro"
sudo /bin/systemctl restart attendpro
sleep 2
systemctl is-active --quiet attendpro && echo "✓ AttendPro is running" || {
    echo "✗ AttendPro did not start. See: journalctl -u attendpro -n 50"; exit 1; }
