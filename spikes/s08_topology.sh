#!/bin/bash
# Spike s08: record the USB path of the Stream Deck Mini and whether its hub can switch port power.
set -u
echo "== ioreg path to the Mini"
ioreg -p IOUSB -w0 | grep -B6 "Stream Deck Mini" | sed 's/^[ |]*//'
echo "== hub IDs on that path"
ioreg -p IOUSB -l -w0 | awk '/\+-o /{name=$0} /"idVendor"|"idProduct"|"locationID"/{print name " :: " $0}' | grep -E "Hub|Stream Deck" | sed 's/^[ |]*//; s/ \{2,\}/ /g'
echo "== uhubctl"
if command -v uhubctl >/dev/null; then uhubctl; else echo "uhubctl not installed (brew install uhubctl); per-port power support unknown"; fi
