#!/bin/bash

die () {
    echo >&2 "$@"
    exit 1
}

[ "$#" -eq 1 ] || die "1 argument required, $# provided"

case $1 in
  0) bcm_pin=17 ;;
  3) bcm_pin=22 ;;
  4) bcm_pin=23 ;;
  5) bcm_pin=24 ;;
  6) bcm_pin=25 ;;
  *) die "Numeric argument between 3-6 required: $1 is not a valid flowd pin" ;;
esac

# the gpio doesn't always initialize properly immediately after boot... 
# these are all hacks to try to kick it alive 
#sleep 15
#/usr/local/bin/gpio unexport $bcm_pin
#/usr/local/bin/gpio edge $bcm_pin rising
#/usr/local/bin/gpio read $1 >> /dev/null 2>&1

echo "starting for pin $1"
/usr/share/kegnet/bin/flowd $1
