#!/usr/bin/env bash
# Flash a Qualcomm device via qdl.
# Usage: flash.sh <meta-dir> [serial]
#
# <meta-dir>  : directory containing prog_firehose_ddr.elf, rawprogram*.xml, patch*.xml
# [serial]    : optional device serial from `qdl list` (recommended when multiple devices present)

set -e

QDL=/local/mnt/workspace/qdl
META_DIR="${1:?Usage: flash.sh <meta-dir> [serial]}"
SERIAL="$2"

if [ ! -f "$META_DIR/prog_firehose_ddr.elf" ]; then
    echo "ERROR: prog_firehose_ddr.elf not found in $META_DIR" >&2
    exit 1
fi

# Build serial flag
SERIAL_FLAG=""
if [ -n "$SERIAL" ]; then
    SERIAL_FLAG="-S $SERIAL"
fi

# Get device serial from qdl list if not provided
if [ -z "$SERIAL" ]; then
    echo "Tip: run '$QDL list' to get the device serial and pass it as the second argument."
fi

cd "$META_DIR"
echo "Flashing from: $META_DIR"

$QDL -s ufs $SERIAL_FLAG \
    prog_firehose_ddr.elf \
    rawprogram0.xml rawprogram1.xml rawprogram2.xml rawprogram3.xml rawprogram4.xml \
    patch0.xml patch1.xml patch2.xml patch3.xml patch4.xml
