#!/usr/bin/env bash
# Database backup (plus uploaded files on Sundays, or with --media).
# Runs daily from attendpro-backup.timer as the `attendpro` user; can also be run by hand:
#     sudo -u attendpro /srv/attendpro/app/deploy/backup.sh
# Restore: pg_restore --clean --if-exists -d db_attendpro /srv/attendpro/backups/db-....dump
set -euo pipefail

DEST=/srv/attendpro/backups
DB=$(grep -E '^DB_NAME=' /srv/attendpro/app/.env | cut -d= -f2-)
STAMP=$(date +%F-%H%M)

# Connects over the local socket as the `attendpro` database role (no password needed)
pg_dump -d "$DB" -Fc -f "$DEST/db-$STAMP.dump"
echo "Saved $DEST/db-$STAMP.dump"

if [ "$(date +%u)" = "7" ] || [ "${1:-}" = "--media" ]; then
    # Uploads, plus private files (registered faces, selfies, organisation backups)
    tar -czf "$DEST/media-$STAMP.tar.gz" -C /srv/attendpro media $( [ -d /srv/attendpro/app/private_data ] && echo app/private_data )
    echo "Saved $DEST/media-$STAMP.tar.gz"
fi

# Keep two weeks of database dumps and eight weeks of media archives
find "$DEST" -name 'db-*.dump' -mtime +14 -delete
find "$DEST" -name 'media-*.tar.gz' -mtime +56 -delete
