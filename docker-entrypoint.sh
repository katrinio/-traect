#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    chown -R traect:traect /data
    exec gosu traect "$@"
fi

exec "$@"
