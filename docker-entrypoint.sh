#!/bin/sh
# Sync the Markdown corpus into the derived SQLite mirror before the server
# starts, so a fresh or restarted container always serves an up-to-date
# library without a manual `recipes sync` step. `sync` self-bootstraps the
# schema, so this also works against an empty data volume.
#
# A non-zero exit means some recipes had errors; we log and start anyway so a
# single bad file can't take the whole app down. Drop the `||` guard to make
# corpus errors a hard startup failure instead.
set -e
recipes sync || echo "WARNING: recipes sync reported errors; starting anyway" >&2
exec "$@"
