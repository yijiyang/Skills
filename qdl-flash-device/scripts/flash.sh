#!/usr/bin/env bash
# Flash a Qualcomm device via qdl.
# Usage: flash.sh <meta-dir> [serial]
#
# <meta-dir>  : directory containing prog_firehose_ddr.elf, rawprogram*.xml, patch*.xml
# [serial]    : optional device serial (auto-prompted when multiple devices are present)

set -euo pipefail

# ── qdl binary resolution ────────────────────────────────────────────────────
QDL_DEFAULT=/local/mnt/workspace/qdl
QDL_DOWNLOAD_URL="https://github.com/linux-msm/qdl/releases/download/v2.5/qdl-binary-ubuntu-24-x64.zip"
QDL_DOWNLOAD_DIR="/local/mnt/workspace"

resolve_qdl() {
    # 1. Honour explicit QDL env var
    if [ -n "${QDL:-}" ] && [ -x "$QDL" ]; then
        return
    fi
    # 2. Use default path if it exists
    if [ -x "$QDL_DEFAULT" ]; then
        QDL="$QDL_DEFAULT"
        return
    fi
    # 3. Try PATH
    if command -v qdl &>/dev/null; then
        QDL=$(command -v qdl)
        return
    fi
    # 4. Auto-download
    echo "qdl binary not found. Downloading from GitHub..."
    local zip="$QDL_DOWNLOAD_DIR/qdl-binary-ubuntu-24-x64.zip"
    curl -fsSL "$QDL_DOWNLOAD_URL" -o "$zip"
    unzip -o "$zip" -d "$QDL_DOWNLOAD_DIR" >/dev/null
    # The zip may contain the binary directly or in a sub-folder; find it.
    local found
    found=$(find "$QDL_DOWNLOAD_DIR" -maxdepth 2 -name "qdl" -type f | head -1)
    if [ -z "$found" ]; then
        echo "ERROR: Could not locate qdl binary after extraction." >&2
        exit 1
    fi
    chmod +x "$found"
    QDL="$found"
    echo "qdl installed at: $QDL"
}

# ── argument parsing ─────────────────────────────────────────────────────────
META_DIR="${1:?Usage: flash.sh <meta-dir> [serial]}"
SERIAL="${2:-}"

# ── validate meta dir ────────────────────────────────────────────────────────
if [ ! -f "$META_DIR/prog_firehose_ddr.elf" ]; then
    echo "ERROR: prog_firehose_ddr.elf not found in $META_DIR" >&2
    exit 1
fi

# ── resolve qdl ──────────────────────────────────────────────────────────────
resolve_qdl

# ── multi-device handling ────────────────────────────────────────────────────
resolve_serial() {
    # If serial already provided, use it directly.
    if [ -n "$SERIAL" ]; then
        echo "Using device serial: $SERIAL"
        return
    fi

    # List devices in EDL mode
    local list_out
    list_out=$("$QDL" list 2>/dev/null || true)

    # Parse serials — qdl list prints lines like:  <serial>  <vid:pid>
    local serials=()
    while IFS= read -r line; do
        local s
        s=$(echo "$line" | awk '{print $1}')
        [ -n "$s" ] && serials+=("$s")
    done <<< "$list_out"

    local count=${#serials[@]}

    if [ "$count" -eq 0 ]; then
        echo "WARNING: No devices reported by 'qdl list'. Proceeding without -S flag." >&2
        SERIAL=""
        return
    fi

    if [ "$count" -eq 1 ]; then
        SERIAL="${serials[0]}"
        echo "Single device detected. Using serial: $SERIAL"
        return
    fi

    # Multiple devices — prompt user
    echo ""
    echo "Multiple devices detected in EDL mode:"
    local i=1
    for s in "${serials[@]}"; do
        echo "  [$i] $s"
        ((i++))
    done
    echo ""
    local choice
    while true; do
        read -rp "Select device [1-$count]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$count" ]; then
            SERIAL="${serials[$((choice-1))]}"
            echo "Selected: $SERIAL"
            break
        fi
        echo "Invalid choice. Enter a number between 1 and $count."
    done
}

resolve_serial

# ── build qdl arguments ──────────────────────────────────────────────────────
SERIAL_FLAG=()
[ -n "$SERIAL" ] && SERIAL_FLAG=(-S "$SERIAL")

# Glob XML files so the script works regardless of how many files exist
cd "$META_DIR"
RAWPROGRAM_FILES=($(ls rawprogram*.xml 2>/dev/null || true))
PATCH_FILES=($(ls patch*.xml 2>/dev/null || true))

if [ ${#RAWPROGRAM_FILES[@]} -eq 0 ]; then
    echo "ERROR: No rawprogram*.xml files found in $META_DIR" >&2
    exit 1
fi

echo ""
echo "Flashing from : $META_DIR"
echo "qdl binary    : $QDL"
echo "Device serial : ${SERIAL:-<none>}"
echo "rawprogram    : ${RAWPROGRAM_FILES[*]}"
echo "patches       : ${PATCH_FILES[*]:-<none>}"
echo ""

"$QDL" -s ufs "${SERIAL_FLAG[@]}" \
    prog_firehose_ddr.elf \
    "${RAWPROGRAM_FILES[@]}" \
    "${PATCH_FILES[@]}"
