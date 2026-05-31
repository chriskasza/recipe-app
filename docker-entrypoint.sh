#!/bin/sh
set -e

APP_ROLE="${APP_ROLE:-web}"

# Roles that serve the derived DB sync the corpus on boot; one-shot CLI does not.
case "$APP_ROLE" in
  web|api)
    recipes sync || echo "WARNING: recipes sync reported errors; starting anyway" >&2
    ;;
esac

exec "$@"
