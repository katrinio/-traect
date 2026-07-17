#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    chown -R traect:traect /app/data
    exec gosu traect "$@"
fi

exec "$@"
