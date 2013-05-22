#!/bin/bash

die () {
    echo >&2 "$@"
    exit 1
}

[ "$#" -eq 1 ] || die "1 argument required, $# provided"

echo "starting for pin $1"
/usr/share/kegnet-client/lib/pourd $1
