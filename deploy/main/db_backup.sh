#!/usr/bin/env bash
# Daily PostgreSQL backup of the main server to S3 (replaces /home/ubuntu/yashAws/db_backup.sh).
#
# Fixes compared with the old script:
#   * The local dump is deleted after a verified S3 upload (the old clean-up line
#     was commented out: 12 dumps x 2.2 GB filled the disk to 100 % on 2026-10-23).
#   * Failures are detected: with pipefail a failing pg_dump is caught (before,
#     only gzip's exit status was checked), and the S3 check tests the upload
#     (before, it tested the `echo` on the line above it).
#   * No password anywhere: pg_dump runs as the postgres system user (peer
#     authentication via sudo), so nothing secret is stored in the script.
#   * Refuses to start when the disk is too full, writes to a temporary name and
#     renames only a complete, gzip-verified dump.
#   * Logs every step with a UTC timestamp to stdout (cron appends it to
#     /home/ubuntu/yashAws/db_backup.log).
#   * Only one run at a time (flock).
#
# INSTALL:
#   1. cp deploy/main/db_backup.sh /home/ubuntu/yashAws/db_backup.sh && chmod 755 it
#   2. crontab (user ubuntu), same time, with the log redirect:
#        40 7 * * * /home/ubuntu/yashAws/db_backup.sh >> /home/ubuntu/yashAws/db_backup.log 2>&1
#   3. Check after the run: tail /home/ubuntu/yashAws/db_backup.log

set -euo pipefail

DB_NAME="warehouse"
S3_URI="s3://databasebackupavc/dbbackup/"
BACKUP_DIR="/tmp/pg_backups"
KEEP_LOCAL=1                                  # newest dumps kept locally after upload
MIN_FREE_GB=6                                 # ~2.5x the current dump size (2.2 GB)
LOG_TAG="db_backup"

log() { echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') ${LOG_TAG}: $*"; }
fail() { log "FAILED: $*"; exit 1; }

exec 9>"/tmp/${LOG_TAG}.lock"
flock -n 9 || fail "another backup is still running"

mkdir -p "$BACKUP_DIR"
free_gb=$(df --output=avail -BG "$BACKUP_DIR" | tail -1 | tr -dc '0-9')
(( free_gb >= MIN_FREE_GB )) || fail "only ${free_gb} GB free on $(df --output=target "$BACKUP_DIR" | tail -1), need ${MIN_FREE_GB} GB"

stamp=$(date +"%Y-%m-%d_%H-%M-%S")
final="$BACKUP_DIR/${DB_NAME}_${stamp}.sql.gz"
partial="$final.partial"
trap 'rm -f "$partial"' EXIT

log "dump started -> $final (free ${free_gb} GB)"
# As the postgres system user (peer authentication): no password needed.
sudo -n -u postgres pg_dump --serializable-deferrable "$DB_NAME" \
  | gzip > "$partial" || fail "pg_dump/gzip exited with an error"
gzip -t "$partial" || fail "gzip integrity check failed"
mv "$partial" "$final"
size=$(stat -c %s "$final")
log "dump complete: $(numfmt --to=iec "$size")"

aws s3 cp --only-show-errors "$final" "$S3_URI" || fail "S3 upload failed (local dump kept: $final)"
remote_size=$(aws s3 ls "$S3_URI$(basename "$final")" | awk '{print $3}') || remote_size=""
[[ "$remote_size" == "$size" ]] || fail "S3 size ${remote_size:-missing} != local $size (local dump kept)"
log "uploaded to $S3_URI ($(numfmt --to=iec "$size"))"

# Keep only the newest KEEP_LOCAL dumps that are confirmed in S3.
mapfile -t old < <(ls -1t "$BACKUP_DIR"/${DB_NAME}_*.sql.gz | tail -n +$((KEEP_LOCAL + 1)))
for f in "${old[@]}"; do
  if aws s3 ls "$S3_URI$(basename "$f")" >/dev/null; then
    rm -f "$f" && log "removed local copy $(basename "$f") (in S3)"
  else
    log "kept $(basename "$f"): not found in S3"
  fi
done
log "done; free now $(df --output=avail -h "$BACKUP_DIR" | tail -1 | tr -d ' ')"
